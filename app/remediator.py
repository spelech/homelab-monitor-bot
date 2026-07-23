import time
import logging
import subprocess
import docker
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import SessionLocal, Incident, Target
from app.notifier import send_followup_notification
from app.qdrant_mem import qdrant_mem

logger = logging.getLogger("Remediator")

def run_remediation(incident_id: str):
    db: Session = SessionLocal()
    try:
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            logger.error(f"Incident {incident_id} not found when starting remediation.")
            return

        target_id = incident.target_id
        proposed_fix = incident.proposed_fix
        root_cause = incident.root_cause

        logger.info(f"Starting remediation for incident {incident_id} (target: {target_id})...")

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
        if target and target.type != "systemd":
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
