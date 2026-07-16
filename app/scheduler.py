import logging
from datetime import datetime
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from app.database import SessionLocal, Target, Incident
from app.notifier import send_incident_notification

logger = logging.getLogger("Scheduler")

def check_deferred_and_ignored():
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()

        # 1. Query deferred incidents that are due for retry
        deferred_incidents = db.query(Incident).filter(
            Incident.status == "DEFERRED",
            Incident.deferred_until < now
        ).all()

        for incident in deferred_incidents:
            logger.info(f"Deferred incident {incident.id} is due for retry. Resetting to PENDING_USER.")
            incident.status = "PENDING_USER"
            incident.deferred_until = None
            db.commit()
            # Re-trigger notification
            send_incident_notification(incident.id)

        # 2. Query ignored targets whose ignore period has expired
        expired_ignores = db.query(Target).filter(
            Target.ignored_until.is_not(None),
            Target.ignored_until < now
        ).all()

        for target in expired_ignores:
            logger.info(f"Ignore period expired for target '{target.id}'. Clearing ignore state.")
            target.ignored_until = None
            db.commit()

        # 3. Query PENDING_USER incidents that haven't been notified/renotified in the last 1 hour
        from datetime import timedelta
        one_hour_ago = now - timedelta(hours=1)
        unresponded_incidents = db.query(Incident).filter(
            Incident.status == "PENDING_USER",
            (Incident.last_notified_at < one_hour_ago) |
            (Incident.last_notified_at.is_(None) & (Incident.created_at < one_hour_ago))
        ).all()

        for incident in unresponded_incidents:
            logger.info(f"Incident {incident.id} for target '{incident.target_id}' remains unresponded for over 1 hour. Renotifying...")
            send_incident_notification(incident.id)

    except Exception as e:
        logger.error(f"Error in scheduler check: {e}")
    finally:
        db.close()

def check_systemd_services():
    db: Session = SessionLocal()
    try:
        import os
        import subprocess
        import uuid
        from app.database import Target, Incident
        from app.investigator import trigger_investigation

        services_str = os.getenv("MONITOR_SYSTEMD_SERVICES", "")
        if not services_str:
            return

        services = [s.strip() for s in services_str.split(",") if s.strip()]
        for service in services:
            res = subprocess.run(["systemctl", "is-active", "--quiet", service])
            if res.returncode != 0:
                logger.warning(f"Systemd service '{service}' is inactive or failed.")

                target = db.query(Target).filter(Target.id == service).first()
                if not target:
                    target = Target(id=service, type="systemd", ignored_until=None)
                    db.add(target)
                    db.commit()
                    db.refresh(target)

                if target.ignored_until and target.ignored_until > datetime.utcnow():
                    continue

                # 3. Check active incident
                active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING", "BLOCKED"]
                active_inc = db.query(Incident).filter(
                    Incident.target_id == service,
                    Incident.status.in_(active_statuses)
                ).first()
                if active_inc:
                    continue

                # 3.5. Circuit Breaker Check
                from datetime import timedelta
                one_hour_ago = datetime.utcnow() - timedelta(minutes=60)
                recent_failures = db.query(Incident).filter(
                    Incident.target_id == service,
                    Incident.status == "FAILED",
                    Incident.completed_at >= one_hour_ago
                ).count()

                if recent_failures >= 2:
                    logger.warning(f"Circuit breaker tripped for systemd service '{service}': {recent_failures} failures in the last 60 minutes.")
                    incident_id = str(uuid.uuid4())
                    new_incident = Incident(
                        id=incident_id,
                        target_id=service,
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
                    continue

                log_res = subprocess.run(
                    ["journalctl", "-u", service, "-n", "50", "--no-pager"],
                    capture_output=True,
                    text=True
                )
                error_logs = log_res.stdout or f"Failed to fetch logs for systemd service {service}."

                incident_id = str(uuid.uuid4())
                incident = Incident(
                    id=incident_id,
                    target_id=service,
                    status="DETECTED",
                    error_logs=error_logs,
                    created_at=datetime.utcnow()
                )
                db.add(incident)
                db.commit()

                logger.info(f"Created systemd failure incident {incident_id} for service '{service}'. Triggering investigation...")
                
                import threading
                threading.Thread(target=trigger_investigation, args=(incident_id,)).start()
    except Exception as e:
        logger.error(f"Error checking systemd services: {e}")
    finally:
        db.close()

def trigger_heartbeat():
    logger.info("Triggering scheduled heartbeat notification.")
    try:
        from app.notifier import send_heartbeat_notification
        send_heartbeat_notification()
    except Exception as e:
        logger.error(f"Failed to send heartbeat notification: {e}")

def start_scheduler():
    import os
    from datetime import datetime, timedelta
    scheduler = BackgroundScheduler()
    # Run checks every 60 seconds
    scheduler.add_job(check_deferred_and_ignored, "interval", seconds=60)
    scheduler.add_job(check_systemd_services, "interval", seconds=60)
    
    # Run heartbeat periodically
    heartbeat_hours = int(os.getenv("HEARTBEAT_INTERVAL_HOURS", "4"))
    scheduler.add_job(trigger_heartbeat, "interval", hours=heartbeat_hours)
    
    # Trigger an initial heartbeat 5 seconds after startup
    startup_time = datetime.now() + timedelta(seconds=5)
    scheduler.add_job(trigger_heartbeat, "date", run_date=startup_time)
    
    scheduler.start()
    logger.info(f"Background Scheduler started (checking every 60s, heartbeat every {heartbeat_hours}h).")
