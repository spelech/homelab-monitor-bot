import os
import re
import json
import time
import logging
import subprocess
import requests
import queue
import threading
from datetime import datetime
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from app.database import SessionLocal, Incident, Target, get_setting
from app.qdrant_mem import qdrant_mem
from app.transcript_logger import log_transcript_event

load_dotenv()

logger = logging.getLogger("Investigator")

_opencode_model_env = os.getenv("OPENCODE_MODEL", "")
if "/" in _opencode_model_env:
    _default_provider, _default_model = _opencode_model_env.split("/", 1)
else:
    _default_provider = "litellm"
    _default_model = _opencode_model_env or "qwen3.7-flash"

AI_EXECUTOR = os.getenv("AI_EXECUTOR", "opencode").lower()
AGY_PATH = os.getenv("AGY_PATH", "/home/steve/.local/bin/agy")
AGY_MODEL = os.getenv("AGY_MODEL", "Gemini 3.5 Flash (Medium)")
OPENCODE_PATH = os.getenv("OPENCODE_PATH", "/home/steve/.nvm/versions/node/v22.17.0/bin/opencode")
OPENCODE_SERVER_URL = os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096")
OPENCODE_PROVIDER_ID = os.getenv("OPENCODE_PROVIDER_ID", _default_provider)
OPENCODE_MODEL_ID = os.getenv("OPENCODE_MODEL_ID", _default_model)

AI_DISPATCH_URL = os.getenv("AI_DISPATCH_URL", "http://localhost:8032/v1").rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", os.getenv("AI_EXECUTOR", "opencode")).lower()
AI_DISPATCH_TIMEOUT = int(os.getenv("AI_DISPATCH_TIMEOUT", "180"))

def call_ai_dispatch_server(prompt: str, model_id: str = None, timeout: int = None) -> tuple[str, float]:
    """Call CLIAgentDispatch OpenAI-compatible HTTP endpoint (:8032/v1/chat/completions)."""
    target_model = model_id or AI_MODEL
    req_timeout = timeout or AI_DISPATCH_TIMEOUT
    url = f"{AI_DISPATCH_URL}/chat/completions"
    
    payload = {
        "model": target_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    
    start_time = time.time()
    resp = requests.post(url, json=payload, timeout=req_timeout)
    duration = time.time() - start_time
    resp.raise_for_status()
    
    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise ValueError("No choices returned from AI dispatch gateway")
    
    content = choices[0].get("message", {}).get("content", "")
    return content, duration

def call_ai_investigate_session(
    target: str,
    error_logs: str,
    notes: str = "",
    executor: str = None,
    max_turns: int = 4,
    timeout: int = None
) -> tuple[dict, float]:
    """Call CLIAgentDispatch SRE interactive investigation endpoint (:8032/v1/investigate)."""
    target_executor = executor or AI_MODEL
    req_timeout = timeout or AI_DISPATCH_TIMEOUT
    url = f"{AI_DISPATCH_URL}/investigate"

    payload = {
        "target": target,
        "exit_code": 1,
        "error_logs": error_logs,
        "notes": notes,
        "executor": target_executor,
        "max_turns": max_turns,
        "timeout": req_timeout
    }

    start_time = time.time()
    resp = requests.post(url, json=payload, timeout=req_timeout)
    duration = time.time() - start_time
    resp.raise_for_status()

    return resp.json(), duration

def call_opencode_server(prompt: str, provider_id: str = None, model_id: str = None, timeout: int = 180) -> str:
    """Call headless opencode serve HTTP API."""
    url = OPENCODE_SERVER_URL.rstrip('/')
    target_provider = provider_id or OPENCODE_PROVIDER_ID
    target_model = model_id or OPENCODE_MODEL_ID
    
    session_res = requests.post(f"{url}/session", json={}, timeout=10)
    session_res.raise_for_status()
    session_id = session_res.json()["id"]

    msg_payload = {
        "model": {
            "providerID": target_provider,
            "modelID": target_model
        },
        "parts": [{"type": "text", "text": prompt}]
    }
    msg_res = requests.post(f"{url}/session/{session_id}/message", json=msg_payload, timeout=timeout)
    msg_res.raise_for_status()

    output_parts = []
    for part in msg_res.json().get("parts", []):
        if part.get("type") == "text":
            output_parts.append(part.get("text", ""))
    return "\n".join(output_parts)

# Thread-safe queue for sequential investigations
investigation_queue = queue.Queue()

def is_target_healthy(target_id: str, target_type: str) -> bool:
    try:
        if target_type == "systemd":
            res = subprocess.run(["systemctl", "is-active", "--quiet", target_id])
            return res.returncode == 0
        else:
            import docker
            docker_client = docker.from_env()
            c = docker_client.containers.get(target_id)
            state = c.attrs.get("State", {})
            is_running = state.get("Running", False)
            health = state.get("Health", {}).get("Status", "none")
            return is_running and health in ["healthy", "none"]
    except Exception as e:
        logger.debug(f"Error checking health for '{target_id}': {e}")
        return False

def check_and_resolve_incident_if_healthy(db: Session, incident: Incident) -> bool:
    target = db.query(Target).filter(Target.id == incident.target_id).first()
    target_type = target.type if target else "docker"
    if is_target_healthy(incident.target_id, target_type):
        logger.info(f"Target '{incident.target_id}' is healthy. Auto-resolving incident {incident.id}.")
        incident.status = "RESOLVED"
        incident.completed_at = datetime.utcnow()
        db.commit()
        return True
    return False

def cleanup_resolved_incidents():
    logger.info("Running post-run queue cleanup to check if other pending incidents are resolved...")
    db: Session = SessionLocal()
    try:
        active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER"]
        incidents = db.query(Incident).filter(Incident.status.in_(active_statuses)).all()
        for inc in incidents:
            check_and_resolve_incident_if_healthy(db, inc)
    except Exception as e:
        logger.error(f"Error cleaning up resolved incidents: {e}")
    finally:
        db.close()

def is_fix_safe_for_autopilot(command: str, category: str = "unknown") -> bool:
    """
    Tiered autopilot safety evaluation:
    Returns True ONLY for low-risk, non-destructive remediation commands
    (e.g., restarting a container/service, bringing up containers with compose, read-only diagnostic checks).
    Returns False for destructive commands, file modifications, deletions, raw scripts,
    or dangerous arguments.
    """
    if not command or not isinstance(command, str):
        return False

    cat = str(category or "").strip().lower()
    if cat in ("destructive", "manual", "security", "unsupported"):
        return False

    # Sanitize markdown code fences, bullets, and commentary
    from app.remediator import sanitize_remediation_command
    clean_cmd = sanitize_remediation_command(command).strip()
    if not clean_cmd:
        return False

    # Check for forbidden shell metacharacters: ;, |, >, <, $, `, (, ), {, }
    # Note: & is allowed only as &&
    forbidden_chars = set(";|><$`(){}[]*?")
    # Also check single & (not part of &&)
    if re.search(r"(?<!&)&(?!&)", clean_cmd):
        return False

    # Allowed command regex patterns for individual statements
    # 1. cd to a container directory: cd /containers/... or cd path
    cd_pattern = re.compile(r"^cd\s+([a-zA-Z0-9_./-]+)$")

    # 2. docker compose restart: docker compose [-f path] restart [services...]
    dc_restart_pattern = re.compile(r"^docker[- ]compose(?:\s+-f\s+[a-zA-Z0-9_./-]+)?\s+restart(?:\s+[a-zA-Z0-9_.-]+)*$")

    # 3. docker compose up: docker compose [-f path] up -d [--force-recreate] [services...]
    dc_up_pattern = re.compile(r"^docker[- ]compose(?:\s+-f\s+[a-zA-Z0-9_./-]+)?\s+up\s+(?:-d\s+--force-recreate|--force-recreate\s+-d|-d)(?:\s+[a-zA-Z0-9_.-]+)*$")

    # 4. docker compose start / docker start
    dc_start_pattern = re.compile(r"^docker[- ]compose(?:\s+-f\s+[a-zA-Z0-9_./-]+)?\s+start(?:\s+[a-zA-Z0-9_.-]+)*$")
    docker_start_pattern = re.compile(r"^docker\s+start(?:\s+[a-zA-Z0-9_.-]+)+$")

    # 5. docker restart [-t sec] [containers...]
    docker_restart_pattern = re.compile(r"^docker\s+restart(?:\s+-t\s+\d+)?(?:\s+[a-zA-Z0-9_.-]+)+$")

    # 6. systemctl restart <service>
    systemctl_restart_pattern = re.compile(r"^systemctl\s+restart\s+[a-zA-Z0-9_.-]+(?:\.service)?$")

    # 7. Diagnostic / verification checks (ps)
    dc_ps_pattern = re.compile(r"^docker[- ]compose(?:\s+-f\s+[a-zA-Z0-9_./-]+)?\s+ps(?:\s+[a-zA-Z0-9_.-]+)*$")
    docker_ps_pattern = re.compile(r"^docker\s+ps(?:\s+--filter\s+[a-zA-Z0-9_=.-]+)*$")

    # 8. Safe sleep (up to 60s)
    sleep_pattern = re.compile(r"^sleep\s+([1-9]|[1-5][0-9]|60)$")

    action_patterns = [
        dc_restart_pattern,
        dc_up_pattern,
        dc_start_pattern,
        docker_start_pattern,
        docker_restart_pattern,
        systemctl_restart_pattern,
    ]

    safe_patterns = action_patterns + [
        cd_pattern,
        dc_ps_pattern,
        docker_ps_pattern,
        sleep_pattern,
    ]

    has_action = False

    # Split into lines and compound statements
    for line in clean_cmd.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Check forbidden characters in line
        if any(ch in forbidden_chars for ch in line):
            return False

        # Split chained commands by &&
        parts = line.split("&&")
        for part in parts:
            stmt = part.strip()
            if not stmt:
                continue

            # Check cd path safety (no path traversal .. or flag)
            m_cd = cd_pattern.match(stmt)
            if m_cd:
                path = m_cd.group(1)
                if ".." in path or path.startswith("-"):
                    return False
                continue

            # Strip harmless surrounding quotes from arguments if present
            stmt_normalized = re.sub(r"[\"']", "", stmt)

            matched = False
            for pattern in safe_patterns:
                if pattern.match(stmt) or pattern.match(stmt_normalized):
                    matched = True
                    if any(ap.match(stmt) or ap.match(stmt_normalized) for ap in action_patterns):
                        has_action = True
                    break

            if not matched:
                return False

    return has_action

def trigger_investigation(incident_id: str):
    logger.info(f"Queueing investigation for incident {incident_id}")
    investigation_queue.put(incident_id)

def run_investigation_logic(db: Session, incident: Incident):
    incident_id = incident.id
    # 1. Update status to INVESTIGATING
    incident.status = "INVESTIGATING"
    db.commit()
    logger.info(f"Updated incident {incident_id} status to INVESTIGATING")

    target = db.query(Target).filter(Target.id == incident.target_id).first()
    is_systemd = (target and target.type == "systemd")

    # 2. Query Qdrant for similar historical fixes
    historical_context = ""
    try:
        match = qdrant_mem.query_similar_fix(incident.target_id, incident.error_logs)
        if match:
            payload = match.metadata
            successful_command = payload.get("successful_command")
            if successful_command:
                target_noun = "systemd service" if is_systemd else "container"
                historical_context = (
                    f"\n\nHistorical context: In the past, a similar issue on this {target_noun} "
                    f"was successfully fixed using this command: {successful_command}. "
                    f"Take this into consideration when proposing your fix."
                )
                logger.info(f"Injecting historical fix context for target '{incident.target_id}'")
    except Exception as q_err:
        logger.error(f"Error querying Qdrant memory: {q_err}")

    # 3. Construct prompt using centralized homelab rules and Docker context
    from app.prompts import build_investigator_prompt
    prompt = build_investigator_prompt(
        target_id=incident.target_id,
        error_logs=incident.error_logs,
        historical_context=historical_context,
        is_systemd=is_systemd
    )

    log_transcript_event(incident_id, "PROMPT_GENERATED", {
        "target_id": incident.target_id,
        "is_systemd": is_systemd,
        "prompt": prompt,
        "historical_context": historical_context
    })

    # 4. Run AI executor via CLIAgentDispatch HTTP with local CLI subprocess fallback
    output = None
    exec_duration = 0.0
    current_executor = AI_MODEL

    # Attempt multi-turn SRE investigation session via CLIAgentDispatch (:8032/v1/investigate)
    if os.getenv("ENABLE_INTERACTIVE_SRE", "true").lower() == "true":
        try:
            logger.info(f"Dispatching interactive SRE session to CLIAgentDispatch ({AI_DISPATCH_URL}/investigate) with executor '{AI_MODEL}'...")
            inv_data, exec_duration = call_ai_investigate_session(
                target=incident.target_id,
                error_logs=incident.error_logs,
                notes=historical_context,
                executor=AI_MODEL,
            )
            if inv_data.get("root_cause") and inv_data.get("proposed_fix"):
                output = json.dumps({
                    "root_cause": inv_data.get("root_cause"),
                    "proposed_fix": inv_data.get("proposed_fix"),
                    "category": inv_data.get("category", "unknown"),
                })
            else:
                output = inv_data.get("raw_output")

            for turn in inv_data.get("transcript", []):
                log_transcript_event(incident_id, "AGENT_TURN", turn)
        except Exception as interactive_err:
            logger.info(f"Interactive SRE session endpoint unavailable ({interactive_err}). Falling back to completions...")
            output = None

    if not output:
        try:
            logger.info(f"Dispatching investigation prompt to CLIAgentDispatch HTTP ({AI_DISPATCH_URL}) with model '{AI_MODEL}'...")
            output, exec_duration = call_ai_dispatch_server(prompt, model_id=AI_MODEL)
        except Exception as dispatch_err:
            logger.warning(f"CLIAgentDispatch HTTP failed ({dispatch_err}). Falling back to direct CLI subprocess execution...")
            start_time = time.time()
            if "opencode" in AI_MODEL:
                logger.info(f"Falling back to opencode CLI at {OPENCODE_PATH} for incident {incident_id}...")
                cmd = [OPENCODE_PATH, "run", "--auto", "--model", f"{OPENCODE_PROVIDER_ID}/{OPENCODE_MODEL_ID}", prompt]
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                    exec_duration = time.time() - start_time
                    if result.returncode == 0:
                        output = result.stdout
                    else:
                        logger.error(f"opencode CLI execution failed: {result.stderr}")
                        incident.status = "FAILED"
                        incident.execution_log = f"opencode CLI error: {result.stderr}"
                        db.commit()
                        log_transcript_event(incident_id, "AI_EXECUTION_FAILED", {"error": str(result.stderr)})
                        return
                except Exception as cli_err:
                    logger.error(f"opencode CLI error: {cli_err}")
                    incident.status = "FAILED"
                    incident.execution_log = f"opencode error: {cli_err}"
                    db.commit()
                    log_transcript_event(incident_id, "AI_EXECUTION_FAILED", {"error": str(cli_err)})
                    return
            elif "agy" in AI_MODEL:
                logger.info(f"Falling back to agy CLI at {AGY_PATH} using {AGY_MODEL} for incident {incident_id}...")
                cmd = [AGY_PATH, "--model", AGY_MODEL, "--dangerously-skip-permissions", "--print", prompt]
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                    exec_duration = time.time() - start_time
                    if result.returncode != 0:
                        logger.error(f"agy execution failed: {result.stderr}")
                        incident.status = "FAILED"
                        incident.execution_log = f"agy error: {result.stderr}"
                        db.commit()
                        log_transcript_event(incident_id, "AI_EXECUTION_FAILED", {"error": str(result.stderr)})
                        return
                    output = result.stdout
                except Exception as agy_err:
                    logger.error(f"agy execution error: {agy_err}")
                    incident.status = "FAILED"
                    incident.execution_log = f"agy error: {agy_err}"
                    db.commit()
                    log_transcript_event(incident_id, "AI_EXECUTION_FAILED", {"error": str(agy_err)})
                    return
            else:
                logger.warning(f"Unrecognized AI_MODEL '{AI_MODEL}' for CLI fallback, defaulting to opencode CLI...")
                cmd = [OPENCODE_PATH, "run", "--auto", "--model", f"{OPENCODE_PROVIDER_ID}/{OPENCODE_MODEL_ID}", prompt]
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                    exec_duration = time.time() - start_time
                    if result.returncode == 0:
                        output = result.stdout
                    else:
                        logger.error(f"CLI execution failed: {result.stderr}")
                        incident.status = "FAILED"
                        incident.execution_log = f"CLI error: {result.stderr}"
                        db.commit()
                        log_transcript_event(incident_id, "AI_EXECUTION_FAILED", {"error": str(result.stderr)})
                        return
                except Exception as cli_err:
                    logger.error(f"CLI error: {cli_err}")
                    incident.status = "FAILED"
                    incident.execution_log = f"CLI error: {cli_err}"
                    db.commit()
                    log_transcript_event(incident_id, "AI_EXECUTION_FAILED", {"error": str(cli_err)})
                    return

    logger.info(f"Received output from {current_executor}: {output}")

    log_transcript_event(incident_id, "AI_THINKING_RAW", {
        "raw_output": output,
        "executor": current_executor,
        "model_id": AI_MODEL,
        "exec_duration": exec_duration
    })

    # Record AI Usage & Spend metrics
    try:
        from app.ai_usage import record_ai_usage
        record_ai_usage(
            incident_id=incident_id,
            executor=current_executor,
            model_id=AI_MODEL,
            prompt_text=prompt,
            completion_text=output or "",
            duration_sec=exec_duration,
            status="SUCCESS" if output else "FAILED"
        )
    except Exception as usage_err:
        logger.warning(f"Failed to record AI usage in investigator: {usage_err}")

    # 5. Parse and scrub JSON
    try:
        json_match = re.search(r"\{.*\}", output, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON block found in output")

        clean_json_str = json_match.group(0)
        data = json.loads(clean_json_str)

        root_cause = data.get("root_cause")
        proposed_fix = data.get("proposed_fix")
        category = data.get("category", "unknown")

        if not root_cause or not proposed_fix:
            raise ValueError("Missing 'root_cause' or 'proposed_fix' in JSON")

        # 6. Save findings to database
        incident.root_cause = root_cause
        incident.proposed_fix = proposed_fix
        incident.category = str(category).lower()

        # Check autopilot mode or auto-approve exception for reverse_proxy outages
        autopilot_enabled = (get_setting("autopilot") == "true")
        autopilot_safe_mode = (get_setting("autopilot_safe_mode") == "true")

        # Check if external domain probe fails
        external_domain_down = False
        ntfy_url = os.getenv("NTFY_URL", "https://ntfy.wileyriley.com")
        try:
            probe_resp = requests.get(ntfy_url, timeout=4)
            if probe_resp.status_code >= 400:
                external_domain_down = True
        except Exception:
            external_domain_down = True

        is_caddy_issue = (
            incident.target_id.lower() == "caddy" or 
            incident.category == "reverse_proxy" or 
            "caddy" in (proposed_fix or "").lower() or 
            "caddyfile" in (proposed_fix or "").lower()
        )

        is_safe = is_fix_safe_for_autopilot(proposed_fix, incident.category or "unknown")
        autopilot_active = (autopilot_enabled or autopilot_safe_mode) and is_safe
        emergency_caddy = (external_domain_down and is_caddy_issue)

        auto_approve = autopilot_active or emergency_caddy

        log_transcript_event(incident_id, "DIAGNOSIS_PARSED", {
            "root_cause": root_cause,
            "proposed_fix": proposed_fix,
            "category": category,
            "is_safe_fix": is_safe,
            "auto_approve": auto_approve
        })

        if auto_approve:
            reason = "Autopilot enabled (safe fix verified)" if autopilot_active else "External domains unreachable & reverse proxy issue detected"
            logger.info(f"Auto-approving remediation ({reason}) for incident {incident_id}")
            incident.status = "FIXING"
            db.commit()

            # Send notification indicating fix is being executed automatically
            from app.notifier import send_incident_notification
            send_incident_notification(incident_id)

            # Trigger remediation in the background
            from app.remediator import run_remediation
            import threading
            threading.Thread(target=run_remediation, args=(incident_id,), daemon=True).start()
        else:
            incident.status = "PENDING_USER"
            db.commit()
            logger.info(f"Successfully processed investigation for incident {incident_id}. Awaiting user approval.")

            # Send notification awaiting user approval
            from app.notifier import send_incident_notification
            send_incident_notification(incident_id)

    except Exception as parse_err:
        logger.error(f"Failed to parse AI output for incident {incident_id}: {parse_err}")
        incident.status = "FAILED"
        incident.execution_log = f"Parsing error: {parse_err}\nRaw output: {output}"
        db.commit()

    except subprocess.TimeoutExpired:
        logger.error(f"agy execution timed out for incident {incident_id}")
        incident.status = "FAILED"
        incident.execution_log = "agy execution timed out"
        db.commit()
    except Exception as e:
        logger.error(f"Error in run_investigation_logic for {incident_id}: {e}")
        incident.status = "FAILED"
        incident.execution_log = f"Error: {e}"
        db.commit()

def queue_worker():
    logger.info("Sequential investigation queue worker thread started.")
    while True:
        incident_id = investigation_queue.get()
        try:
            logger.info(f"Processing queued incident {incident_id}...")
            db: Session = SessionLocal()
            try:
                incident = db.query(Incident).filter(Incident.id == incident_id).first()
                if incident:
                    # Pre-check: if the target is already resolved/healthy, skip investigation
                    if check_and_resolve_incident_if_healthy(db, incident):
                        logger.info(f"Incident {incident_id} target '{incident.target_id}' is already healthy. Skipping investigation.")
                        continue
                    
                    # Run the investigation
                    run_investigation_logic(db, incident)
            except Exception as inner_e:
                logger.error(f"Error in queue worker for incident {incident_id}: {inner_e}")
            finally:
                db.close()
            
            # Post-run cleanup: check if others are resolved
            cleanup_resolved_incidents()
        except Exception as e:
            logger.error(f"Critical error in queue_worker loop: {e}")
        finally:
            investigation_queue.task_done()

# Start worker thread on module load
worker_thread = threading.Thread(target=queue_worker, daemon=True)
worker_thread.start()
