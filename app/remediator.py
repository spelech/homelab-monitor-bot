import re
import time
import logging
import subprocess
import docker
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import SessionLocal, Incident, Target
from app.notifier import send_followup_notification
from app.qdrant_mem import qdrant_mem
from app.transcript_logger import log_transcript_event

logger = logging.getLogger("Remediator")

VALID_COMMAND_STARTERS = {
    "docker", "docker-compose", "systemctl", "journalctl", "cd", "curl", "chown", "chmod",
    "rm", "kill", "fusermount", "umount", "mount", "ping", "apt", "apt-get",
    "mkdir", "cp", "mv", "touch", "cat", "echo", "printf", "sed", "grep",
    "awk", "find", "sleep", "export", "source", "service", "sudo", "python",
    "python3", "pip", "pip3", "npm", "npx", "git", "nc", "wget", "smartctl",
    "sync", "pkill", "killall", "systemd-run", "ip", "ss", "netstat", "tail",
    "head", "ls", "sh", "bash", "env", "df", "du", "tar", "gzip", "gunzip",
    "unzip", "ln", "tee", "date", "which", "whereis", "ps", "top", "htop", "uptime",
    "reboot", "shutdown", "poweroff", "init", "node"
}


def _is_executable_statement(stmt: str) -> bool:
    """Checks if a statement starts with an executable binary, script, or environment variable assignment."""
    if not stmt or not isinstance(stmt, str):
        return False
    s = stmt.strip()
    if not s or s.startswith("#"):
        return False

    tokens = s.split()
    if not tokens:
        return False

    # Handle environment variables prefix e.g. FOO=bar cmd
    tok_idx = 0
    while tok_idx < len(tokens) and "=" in tokens[tok_idx] and not tokens[tok_idx].startswith("-"):
        tok_idx += 1

    if tok_idx >= len(tokens):
        return False

    first = tokens[tok_idx].strip("\"'();`")

    # If first token is sudo, nohup, exec, check next token
    if first.lower() in ("sudo", "nohup", "exec") and tok_idx + 1 < len(tokens):
        first = tokens[tok_idx + 1].strip("\"'();`")

    first_lower = first.lower()

    if first_lower in VALID_COMMAND_STARTERS:
        return True

    if first.startswith(("./", "/", "~/", "../")):
        return True

    if first.endswith(".sh") or first.endswith(".py"):
        return True

    return False


def sanitize_remediation_command(proposed_fix: Optional[str]) -> str:
    """
    Sanitizes LLM-proposed remediation fixes by:
    - Stripping markdown code fences (```bash, ```sh, etc.)
    - Stripping leading numbers (1. , 1) ), bullet markers (- , * , + ), and prompt markers ($ , > )
    - Extracting executable shell statements starting with known binaries or scripts
    - Discarding non-executable commentary lines
    """
    if not proposed_fix or not isinstance(proposed_fix, str):
        return ""

    sanitized_lines = []
    lines = proposed_fix.strip().splitlines()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # Skip markdown code fences
        if line.startswith("```") or line.startswith("~~~"):
            continue

        # Skip pure shell comments
        if line.startswith("#"):
            continue

        # Strip surrounding backticks if the entire line is wrapped in backticks
        if line.startswith("`") and line.endswith("`") and len(line) >= 2:
            line = line[1:-1].strip()

        # 1. Direct check: is the line already an executable statement?
        if _is_executable_statement(line):
            sanitized_lines.append(line)
            continue

        # 2. Strip leading numbers, bullets, or prompt symbols
        stripped_line = re.sub(r"^(?:[\d]+[\.\)]|\*|-|\+|\$|>)\s*", "", line).strip()

        # Strip surrounding backticks if any
        if stripped_line.startswith("`") and stripped_line.endswith("`") and len(stripped_line) >= 2:
            stripped_line = stripped_line[1:-1].strip()

        if _is_executable_statement(stripped_line):
            sanitized_lines.append(stripped_line)
            continue

        # 3. Check for colon-separated commands:
        # e.g., "1. Restart Radarr4K to clear error: cd /containers/media_content && docker compose restart radarr4k"
        if ":" in stripped_line:
            parts = stripped_line.split(":")
            matched_colon = False
            for idx in range(1, len(parts)):
                candidate = ":".join(parts[idx:]).strip()
                if candidate.startswith("`") and candidate.endswith("`") and len(candidate) >= 2:
                    candidate = candidate[1:-1].strip()
                if _is_executable_statement(candidate):
                    sanitized_lines.append(candidate)
                    matched_colon = True
                    break
            if matched_colon:
                continue

        # 4. Check for backtick-enclosed commands within commentary:
        # e.g., "Run `docker compose restart radarr` to fix"
        backtick_matches = re.findall(r"`([^`]+)`", stripped_line)
        matched_backtick = False
        for match in backtick_matches:
            match = match.strip()
            if _is_executable_statement(match):
                sanitized_lines.append(match)
                matched_backtick = True
                break
        if matched_backtick:
            continue

        # Otherwise, discard non-executable commentary lines

    return "\n".join(sanitized_lines).strip()


def run_remediation(incident_id: str):
    db: Session = SessionLocal()
    try:
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            logger.error(f"Incident {incident_id} not found when starting remediation.")
            return

        target_id = incident.target_id
        raw_fix = incident.proposed_fix or ""
        proposed_fix = sanitize_remediation_command(raw_fix)
        incident.proposed_fix = proposed_fix
        root_cause = incident.root_cause

        logger.info(f"Starting remediation for incident {incident_id} (target: {target_id})...")

        if not proposed_fix:
            logger.warning(f"No executable remediation commands found for incident {incident_id} (target '{target_id}'): {raw_fix}")
            incident.status = "FAILED"
            incident.completed_at = datetime.utcnow()
            incident.execution_log = f"Remediation FAILED: No executable commands could be parsed from proposed fix:\n{raw_fix}"
            db.commit()
            send_followup_notification(
                incident_id,
                f"Remediation failed for container '{target_id}': No executable commands could be parsed from proposed fix.",
                success=False
            )
            return

        # 1.3. Dependency Check: check if any parent dependencies have active incidents
        from app.dependencies import check_parent_incidents
        active_parents = check_parent_incidents(target_id, db)
        if active_parents:
            parent_names = ", ".join([p.target_id for p in active_parents])
            logger.info(f"Target '{target_id}' has unresolved parent dependencies: {parent_names}. Pausing remediation.")
            incident.status = "PENDING_USER"
            incident.execution_log = f"Remediation paused: Unresolved parent dependencies: {parent_names}."
            db.commit()
            return

        # 1.5. Command Safety Validation
        is_safe = True
        violation = ""
        blacklist = [
            (r"\brm\s+-[a-zA-Z]*rf?\b", "Recursive deletion command (rm -rf) detected."),
            (r"docker\s+(system|volume|container|image|builder)\s+prune", "Docker resource prune command detected."),
            (r"\breboot\b|\bpoweroff\b|\bshutdown\b|\binit\s+[06]\b", "Host power/reboot command detected."),
            (r"docker\s+kill\s+", "Docker kill command detected."),
            (r"\bmv\s+.*?\s+/dev/null\b", "Moving files to /dev/null detected.")
        ]
        
        import re
        for pattern, desc in blacklist:
            if re.search(pattern, proposed_fix, re.IGNORECASE):
                is_safe = False
                violation = desc
                break

        if not is_safe:
            logger.warning(f"UNSAFE command blocked for target '{target_id}': {proposed_fix} ({violation})")
            incident.status = "BLOCKED"
            incident.execution_log = f"Remediation BLOCKED: Unsafe command verification failed: {violation}"
            db.commit()
            log_transcript_event(incident_id, "REMEDIATION_BLOCKED", {
                "target_id": target_id,
                "command": proposed_fix,
                "violation": violation
            })
            
            # Send alert notification
            from app.notifier import send_incident_notification
            send_incident_notification(incident_id)
            return

        # 1.7. Update status to FIXING
        incident.status = "FIXING"
        db.commit()

        # 2. Execute proposed fix bash commands
        logger.info(f"Executing bash command: {proposed_fix}")
        result = subprocess.run(
            proposed_fix,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60
        )

        stdout = result.stdout
        stderr = result.stderr
        exit_code = result.returncode

        logger.info(f"Proposed fix execution complete. Exit code: {exit_code}")
        logger.info(f"Stdout: {stdout}")
        logger.info(f"Stderr: {stderr}")

        log_transcript_event(incident_id, "REMEDIATION_EXECUTION", {
            "target_id": target_id,
            "command": proposed_fix,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr
        })

        # Save outputs to execution log
        execution_log = (
            f"--- Command executed ---\n{proposed_fix}\n\n"
            f"--- Exit Code ---\n{exit_code}\n\n"
            f"--- Stdout ---\n{stdout}\n\n"
            f"--- Stderr ---\n{stderr}"
        )
        incident.execution_log = execution_log
        db.commit()

        # 3. Wait 10 seconds for container state to stabilize
        logger.info("Waiting 10 seconds for container to stabilize...")
        time.sleep(10)

        # 4. Verify health (Uptime Kuma URL label probe -> process health fallback)
        is_healthy = False
        status_detail = ""
        
        # Check if the target is a docker container and has a kuma url label
        kuma_url = None
        target = db.query(Target).filter(Target.id == target_id).first()
        if target and target.type not in ["systemd", "system_mount"]:
            try:
                client = docker.from_env()
                container = client.containers.get(target_id)
                for k, v in container.labels.items():
                    if k.startswith("kuma.") and k.endswith(".http.url"):
                        kuma_url = v
                        break
            except Exception as label_err:
                logger.debug(f"Failed to fetch docker labels for kuma verification: {label_err}")

        if kuma_url:
            logger.info(f"Verifying target health via Uptime Kuma URL: {kuma_url}")
            try:
                import requests
                resp = requests.get(kuma_url, timeout=5, verify=False)
                # 2xx, 3xx, and 401 are considered up/healthy
                if resp.status_code < 400 or resp.status_code == 401:
                    is_healthy = True
                    status_detail = f"healthy via web probe (HTTP {resp.status_code})"
                else:
                    status_detail = f"unhealthy via web probe (HTTP {resp.status_code})"
            except Exception as http_err:
                status_detail = f"unhealthy: web probe failed: {http_err}"
                logger.warning(status_detail)

            # If web probe failed, check if Caddy is down or throwing config errors.
            # If Caddy is the reason web probe failed, ignore web probe failure for this app and rely on container process check instead.
            if not is_healthy and target_id != "caddy":
                caddy_down = False
                try:
                    client = docker.from_env()
                    caddy_cont = client.containers.get("caddy")
                    if caddy_cont.status != "running":
                        caddy_down = True
                    else:
                        caddy_val = caddy_cont.exec_run("caddy validate --config /etc/caddy/Caddyfile")
                        if caddy_val.exit_code != 0:
                            caddy_down = True
                except Exception:
                    caddy_down = True

                if caddy_down:
                    logger.warning(f"Web probe failed for '{target_id}', but Caddy reverse proxy is down/invalid. Ignoring web probe and falling back to process status.")
                    kuma_url = None  # Reset so process check takes over

        if not is_healthy:
            try:
                if target and target.type == "systemd":
                    res = subprocess.run(["systemctl", "is-active", "--quiet", target_id])
                    if res.returncode == 0:
                        is_healthy = True
                        status_detail = "active (running)"
                    else:
                        status_detail = "inactive/failed"
                elif target and target.type == "system_mount":
                    from app.system_health import probe_mount
                    mount_path = target_id.replace("mount:", "")
                    probe_res = probe_mount(mount_path, timeout=3.0)
                    if probe_res.get("healthy"):
                        is_healthy = True
                        status_detail = f"mount healthy ({mount_path})"
                    else:
                        status_detail = f"mount unhealthy: {probe_res.get('error')}"
                else:
                    client = docker.from_env()
                    container = client.containers.get(target_id)
                    state = container.attrs.get("State", {})
                    running = state.get("Running", False)
                    health = state.get("Health", {}).get("Status", "none")

                    if running:
                        if health == "none" or health == "healthy":
                            is_healthy = True
                            status_detail = f"running (health: {health})"
                        else:
                            status_detail = f"running but health status is '{health}'"
                    else:
                        status_detail = f"not running (status: {state.get('Status')})"
            except Exception as check_err:
                status_detail = f"failed to check target state: {check_err}"
                logger.error(status_detail)

        # 5. Handle success/failure state update & notifications
        log_transcript_event(incident_id, "POST_VERIFICATION", {
            "target_id": target_id,
            "is_healthy": is_healthy,
            "status_detail": status_detail,
        })

        if is_healthy:
            logger.info(f"Target '{target_id}' verified healthy ({status_detail}). Marking RESOLVED.")
            incident.status = "RESOLVED"
            incident.completed_at = datetime.utcnow()
            db.commit()

            # Learn successful resolution in Qdrant (Phase 6)
            try:
                qdrant_mem.learn_incident(incident_id, target_id, root_cause, proposed_fix)
            except Exception as q_err:
                logger.error(f"Failed to save incident to Qdrant memory: {q_err}")

            # Send success notification
            msg = (
                f"Container '{target_id}' has been successfully resolved.\n\n"
                f"Status: {status_detail}\n\n"
                f"Command output:\n{stdout}"
            )
            send_followup_notification(incident_id, msg, success=True)
        else:
            logger.error(f"Target '{target_id}' verification failed: {status_detail}. Marking FAILED.")
            incident.status = "FAILED"
            incident.completed_at = datetime.utcnow()
            db.commit()

            # Send failure notification
            msg = (
                f"Failed to resolve issue on container '{target_id}'. Container is {status_detail}.\n\n"
                f"Exit Code: {exit_code}\n"
                f"Stderr:\n{stderr}"
            )
            send_followup_notification(incident_id, msg, success=False)

    except subprocess.TimeoutExpired:
        logger.error(f"Remediation timed out for incident {incident_id}")
        incident.status = "FAILED"
        incident.completed_at = datetime.utcnow()
        incident.execution_log = f"Remediation timed out.\nProposed fix:\n{proposed_fix}"
        db.commit()
        send_followup_notification(
            incident_id,
            f"Remediation execution timed out for container '{target_id}'.",
            success=False
        )
    except Exception as e:
        logger.error(f"Error in run_remediation for {incident_id}: {e}")
        if 'incident' in locals() and incident:
            incident.status = "FAILED"
            incident.completed_at = datetime.utcnow()
            incident.execution_log = f"Remediation error: {e}"
            db.commit()
            send_followup_notification(
                incident_id,
                f"Error executing remediation for container '{target_id}': {e}",
                success=False
            )
    finally:
        db.close()
