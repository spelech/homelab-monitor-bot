import os
import re
import json
import logging
import subprocess
import requests
import queue
import threading
from datetime import datetime
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from app.database import SessionLocal, Incident, Target
from app.qdrant_mem import qdrant_mem

load_dotenv()

logger = logging.getLogger("Investigator")

AI_EXECUTOR = os.getenv("AI_EXECUTOR", "agy").lower()
AGY_PATH = os.getenv("AGY_PATH", "/home/steve/.local/bin/agy")
OPENCODE_PATH = os.getenv("OPENCODE_PATH", "/home/steve/.nvm/versions/node/v22.17.0/bin/opencode")
OPENCODE_SERVER_URL = os.getenv("OPENCODE_SERVER_URL", "http://localhost:8447")

def call_opencode_server(prompt: str, timeout: int = 180) -> str:
    """Call headless opencode serve HTTP API."""
    url = OPENCODE_SERVER_URL.rstrip('/')
    session_res = requests.post(f"{url}/session", json={}, timeout=10)
    session_res.raise_for_status()
    session_id = session_res.json()["id"]

    msg_payload = {"parts": [{"type": "text", "text": prompt}]}
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

    # 3. Construct prompt for agy
    if is_systemd:
        prompt = (
            f"Systemd service failure detected on '{incident.target_id}'.\n"
            f"Error Logs:\n{incident.error_logs}{historical_context}\n\n"
            "You are an SRE bot. Focus strictly on diagnosing this systemd service failure by inspecting its configuration, journalctl logs, and service status. "
            "Do NOT research, grep, or search for the 'agy' command or its flags (like --dangerously-skip-permissions) on the system. "
            "Output ONLY valid JSON with exactly three keys: "
            "'root_cause' (a string explaining the issue), "
            "'proposed_fix' (a string containing valid bash commands to fix it), and "
            "'category' (a string classifying the issue into one of: 'network', 'reverse_proxy', 'permissions', 'settings', 'database', 'unknown'). "
            "Do not include markdown formatting or backticks."
        )
    else:
        prompt = (
            f"Container failure detected on '{incident.target_id}'.\n"
            f"Error Logs:\n{incident.error_logs}{historical_context}\n\n"
            "You are an SRE bot. Focus strictly on diagnosing this container failure by inspecting its configuration, files, and Docker logs. "
            "Do NOT research, grep, or search for the 'agy' command or its flags (like --dangerously-skip-permissions) on the system. "
            "Output ONLY valid JSON with exactly three keys: "
            "'root_cause' (a string explaining the issue), "
            "'proposed_fix' (a string containing valid bash commands to fix it), and "
            "'category' (a string classifying the issue into one of: 'network', 'reverse_proxy', 'permissions', 'settings', 'database', 'unknown'). "
            "Do not include markdown formatting or backticks."
        )

    # 4. Run AI executor (HTTP API or CLI Subprocess)
    output = None
    current_executor = os.getenv("AI_EXECUTOR", "agy").lower()
    if current_executor == "opencode":
        try:
            logger.info(f"Attempting opencode serve HTTP API at {OPENCODE_SERVER_URL} for incident {incident_id}...")
            output = call_opencode_server(prompt)
        except Exception as api_err:
            logger.warning(f"opencode serve HTTP API failed: {api_err}. Falling back to CLI subprocess...")
            cmd = [OPENCODE_PATH, "run", "--auto", prompt]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                if result.returncode == 0:
                    output = result.stdout
                else:
                    logger.error(f"opencode CLI execution failed: {result.stderr}")
                    incident.status = "FAILED"
                    incident.execution_log = f"opencode CLI error: {result.stderr}"
                    db.commit()
                    return
            except Exception as cli_err:
                logger.error(f"opencode CLI error: {cli_err}")
                incident.status = "FAILED"
                incident.execution_log = f"opencode error: {cli_err}"
                db.commit()
                return
    else:
        logger.info(f"Calling agy CLI at {AGY_PATH} using gemini-3.5-flash-medium for incident {incident_id}...")
        cmd = [AGY_PATH, "--model", "gemini-3.5-flash-medium", "--dangerously-skip-permissions", "--print", prompt]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode != 0:
                logger.error(f"agy execution failed: {result.stderr}")
                incident.status = "FAILED"
                incident.execution_log = f"agy error: {result.stderr}"
                db.commit()
                return
            output = result.stdout
        except Exception as agy_err:
            logger.error(f"agy execution error: {agy_err}")
            incident.status = "FAILED"
            incident.execution_log = f"agy error: {agy_err}"
            db.commit()
            return

    logger.info(f"Received output from {current_executor}: {output}")

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
        from app.database import get_setting
        autopilot_enabled = (get_setting("autopilot") == "true")

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

        auto_approve = autopilot_enabled or (external_domain_down and is_caddy_issue)

        if auto_approve:
            reason = "Autopilot enabled" if autopilot_enabled else "External domains unreachable & reverse proxy issue detected"
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
