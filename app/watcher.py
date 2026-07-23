import os
import threading
import time
import logging
import uuid
from datetime import datetime
import docker
from sqlalchemy.orm import Session
from app.database import SessionLocal, Target, Incident
from app.investigator import trigger_investigation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DockerWatcher")

def run_watcher():
    while True:
        try:
            logger.info("Connecting to Docker daemon...")
            client = docker.from_env()
            logger.info("Listening for Docker container events...")

            # Non-polling events stream
            events_stream = client.events(
                decode=True,
                filters={'type': 'container'}
            )

            for event in events_stream:
                action = event.get("Action")
                actor = event.get("Actor", {})
                attributes = actor.get("Attributes", {})
                container_name = attributes.get("name")
                container_id = event.get("id")

                if not container_name:
                    continue

                # Skip events for monitorbot and non-compose containers to avoid feedback loops
                if "monitorbot" in container_name or "com.docker.compose.project" not in attributes:
                    continue


                is_failure = False
                reason = ""

                # Condition 1: Container die event with non-zero exit code
                if action == "die":
                    exit_code = attributes.get("exitCode", "0")
                    if exit_code != "0":
                        is_failure = True
                        reason = f"Container died with exit code {exit_code}"

                # Condition 2: Container health status becomes unhealthy
                elif action == "health_status: unhealthy":
                    is_failure = True
                    reason = "Container health status became unhealthy"

                if is_failure:
                    logger.warning(f"Failure detected on target '{container_name}': {reason}")
                    process_failure(client, container_name, container_id, reason)

        except docker.errors.DockerException as de:
            logger.error(f"Docker connection error: {de}. Retrying in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected watcher error: {e}. Retrying in 5 seconds...")
            time.sleep(5)

def process_failure(docker_client, container_name: str, container_id: str, reason: str):
    db: Session = SessionLocal()
    try:
        # 1. Fetch or create target
        target = db.query(Target).filter(Target.id == container_name).first()
        if not target:
            target = Target(id=container_name, type="docker", ignored_until=None)
            db.add(target)
            db.commit()
            db.refresh(target)

        # 2.5. Caddy Gatekeeper Check:
        # If target is NOT caddy, check if caddy currently has an active incident.
        # If Caddy is failing/down, suppress incident creation for downstream containers.
        if container_name != "caddy":
            active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING", "BLOCKED"]
            caddy_active = db.query(Incident).filter(
                Incident.target_id == "caddy",
                Incident.status.in_(active_statuses)
            ).first()
            if caddy_active:
                logger.info(f"Cascading suppression: Caddy reverse proxy has active incident {caddy_active.id}. Skipping incident creation for target '{container_name}'.")
                return

        # 3. Check if there is already an active incident for this target
        active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING", "BLOCKED"]

        active_incident = db.query(Incident).filter(
            Incident.target_id == container_name,
            Incident.status.in_(active_statuses)
        ).first()

        if active_incident:
            logger.info(f"Target '{container_name}' already has active incident {active_incident.id} ({active_incident.status}). Skipping.")
            return

        # 3.5. Circuit Breaker Check: Check for repeated failures in the last 60 minutes
        from datetime import timedelta
        one_hour_ago = datetime.utcnow() - timedelta(minutes=60)
        recent_failures = db.query(Incident).filter(
            Incident.target_id == container_name,
            Incident.status == "FAILED",
            Incident.completed_at >= one_hour_ago
        ).count()

        if recent_failures >= 2:
            logger.warning(f"Circuit breaker tripped for target '{container_name}': {recent_failures} failures in the last 60 minutes.")
            incident_id = str(uuid.uuid4())
            new_incident = Incident(
                id=incident_id,
                target_id=container_name,
                status="BLOCKED",
                error_logs=f"Circuit breaker tripped: {recent_failures} failures in the last 60 minutes. Automatic recovery disabled.",
                created_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )
            db.add(new_incident)
            db.commit()
            
            # Send notification
            from app.notifier import send_incident_notification
            send_incident_notification(incident_id)
            return

        # 4. Fetch logs
        error_logs = ""
        try:
            container = docker_client.containers.get(container_id)
            # Fetch last 50 lines of logs
            logs_bytes = container.logs(tail=50, stdout=True, stderr=True)
            error_logs = logs_bytes.decode("utf-8", errors="replace")
        except Exception as log_err:
            error_logs = f"Could not retrieve container logs: {log_err}"

        # Combine failure reason and logs
        full_logs = f"Reason: {reason}\n\n--- Container Logs ---\n{error_logs}"

        # 5. Create new incident
        incident_id = str(uuid.uuid4())
        new_incident = Incident(
            id=incident_id,
            target_id=container_name,
            status="DETECTED",
            error_logs=full_logs
        )
        db.add(new_incident)
        db.commit()
        logger.info(f"Created new incident {incident_id} for target '{container_name}'")

        # Check silent mode setting
        from app.database import get_setting
        if get_setting("silent_mode") == "true":
            logger.info("Silent mode is enabled. Skipping investigation and notifications.")
            return

        # 6. Trigger Phase 2 Investigation in a background thread
        threading.Thread(target=trigger_investigation, args=(incident_id,), daemon=True).start()

    except Exception as e:
        logger.error(f"Error processing failure for '{container_name}': {e}")
    finally:
        db.close()

def start_watcher_thread():
    t = threading.Thread(target=run_watcher, daemon=True)
    t.start()
    logger.info("Docker Watcher thread started.")
