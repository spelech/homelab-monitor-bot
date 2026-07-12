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

    except Exception as e:
        logger.error(f"Error in scheduler check: {e}")
    finally:
        db.close()

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Run check every 60 seconds
    scheduler.add_job(check_deferred_and_ignored, "interval", seconds=60)
    scheduler.start()
    logger.info("Background Scheduler started (checking every 60s).")
