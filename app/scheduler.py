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
    # Run check every 60 seconds
    scheduler.add_job(check_deferred_and_ignored, "interval", seconds=60)
    
    # Run heartbeat periodically
    heartbeat_hours = int(os.getenv("HEARTBEAT_INTERVAL_HOURS", "24"))
    scheduler.add_job(trigger_heartbeat, "interval", hours=heartbeat_hours)
    
    # Trigger an initial heartbeat 5 seconds after startup
    startup_time = datetime.now() + timedelta(seconds=5)
    scheduler.add_job(trigger_heartbeat, "date", run_date=startup_time)
    
    scheduler.start()
    logger.info(f"Background Scheduler started (checking every 60s, heartbeat every {heartbeat_hours}h).")
