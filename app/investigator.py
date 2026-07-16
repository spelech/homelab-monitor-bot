import os
import re
import json
import logging
import subprocess
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from app.database import SessionLocal, Incident, Target
from app.qdrant_mem import qdrant_mem

load_dotenv()

logger = logging.getLogger("Investigator")

AI_EXECUTOR = os.getenv("AI_EXECUTOR", "agy").lower()
AGY_PATH = os.getenv("AGY_PATH", "/home/steve/.local/bin/agy")
OPENCODE_PATH = os.getenv("OPENCODE_PATH", "/home/steve/.nvm/versions/node/v22.17.0/bin/opencode")

def trigger_investigation(incident_id: str):
    db: Session = SessionLocal()
    try:
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            logger.error(f"Incident {incident_id} not found in database.")
            return

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

        # 4. Run AI executor subprocess
        if AI_EXECUTOR == "opencode":
            logger.info(f"Calling opencode CLI at {OPENCODE_PATH} for incident {incident_id}...")
            cmd = [OPENCODE_PATH, "run", "--auto", prompt]
        else:
            logger.info(f"Calling agy CLI at {AGY_PATH} for incident {incident_id}...")
            cmd = [AGY_PATH, "--dangerously-skip-permissions", "--print", prompt]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180  # 3 minutes timeout
        )

        if result.returncode != 0:
            logger.error(f"{AI_EXECUTOR} execution failed: {result.stderr}")
            incident.status = "FAILED"
            incident.execution_log = f"{AI_EXECUTOR} error: {result.stderr}"
            db.commit()
            return

        output = result.stdout
        logger.info(f"Received output from {AI_EXECUTOR}: {output}")

        # 5. Parse and scrub JSON
        try:
            # Regex to match JSON block
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

            # Check autopilot mode
            from app.database import get_setting
            autopilot_enabled = (get_setting("autopilot") == "true")

            if autopilot_enabled:
                incident.status = "FIXING"
                db.commit()
                logger.info(f"Autopilot enabled. Automatically executing fix for incident {incident_id}")

                # Send notification indicating autopilot is running the fix
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
            logger.error(f"Failed to parse agy output for incident {incident_id}: {parse_err}")
            incident.status = "FAILED"
            incident.execution_log = f"Parsing error: {parse_err}\nRaw output: {output}"
            db.commit()

    except subprocess.TimeoutExpired:
        logger.error(f"agy execution timed out for incident {incident_id}")
        incident.status = "FAILED"
        incident.execution_log = "agy execution timed out"
        db.commit()
    except Exception as e:
        logger.error(f"Error in trigger_investigation for {incident_id}: {e}")
        if 'incident' in locals() and incident:
            incident.status = "FAILED"
            incident.execution_log = f"Error: {e}"
            db.commit()
    finally:
        db.close()
