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

        # 3. Check for stale PENDING_USER incidents
        from datetime import timedelta
        import docker

        twenty_four_hours_ago = now - timedelta(hours=24)
        one_hour_ago = now - timedelta(hours=1)

        pending_incidents = db.query(Incident).filter(Incident.status == "PENDING_USER").all()

        from app.database import check_maintenance_status
        is_maint, _ = check_maintenance_status(db)

        try:
            docker_client = docker.from_env()
        except Exception:
            docker_client = None

        for incident in pending_incidents:
            # Auto-expire incidents older than 24h
            if incident.created_at < twenty_four_hours_ago:
                logger.info(f"Incident {incident.id} for target '{incident.target_id}' is over 24h old. Marking EXPIRED.")
                incident.status = "EXPIRED"
                db.commit()
                continue

            if is_maint:
                # Skip health check auto-resolution and re-notification while in maintenance mode
                continue

            # Auto-resolve incident if target container is currently healthy and running
            if docker_client:
                try:
                    c = docker_client.containers.get(incident.target_id)
                    state = c.attrs.get("State", {})
                    is_running = state.get("Running", False)
                    health = state.get("Health", {}).get("Status", "none")

                    if is_running and health in ["healthy", "none"]:
                        logger.info(f"Target '{incident.target_id}' is currently healthy & running. Auto-resolving incident {incident.id}.")
                        incident.status = "RESOLVED"
                        incident.completed_at = now
                        db.commit()
                        continue
                except Exception:
                    pass

            # Renotify unresponded pending incidents once per hour
            last_notified = incident.last_notified_at or incident.created_at
            if last_notified < one_hour_ago:
                logger.info(f"Incident {incident.id} for target '{incident.target_id}' remains unresponded. Renotifying...")
                send_incident_notification(incident.id)

    except Exception as e:
        logger.error(f"Error in scheduler check: {e}")
    finally:
        db.close()

def check_systemd_services():
    db: Session = SessionLocal()
    try:
        from app.database import check_maintenance_status
        is_maint, maint_reason = check_maintenance_status(db)
        if is_maint:
            logger.info(f"Skipping systemd service checks: {maint_reason}")
            return

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

def run_daily_sre_audit():
    logger.info("Triggering scheduled daily SRE stack log audit.")
    db: Session = SessionLocal()
    try:
        from app.database import check_maintenance_status
        is_maint, maint_reason = check_maintenance_status(db)
        if is_maint:
            logger.info(f"Skipping daily SRE audit due to maintenance mode: {maint_reason}")
            return

        from app.stack_watcher import stack_watcher_manager
        results = stack_watcher_manager.audit_all_stacks()
        action_required = [r for r in results if r.get("status") == "ACTION_REQUIRED"]
        logger.info(
            f"Daily SRE stack audit completed. {len(results)} stack(s) checked, "
            f"{len(action_required)} action(s) required."
        )
    except Exception as e:
        logger.error(f"Error during daily SRE stack audit: {e}")
    finally:
        db.close()

def run_storage_mount_audit():
    logger.info("Triggering scheduled proactive storage and FUSE mount health audit.")
    db: Session = SessionLocal()
    try:
        from app.database import check_maintenance_status
        is_maint, maint_reason = check_maintenance_status(db)
        if is_maint:
            logger.info(f"Skipping storage and mount audit due to maintenance mode: {maint_reason}")
            return

        from app.system_health import audit_storage_and_mounts
        audit_storage_and_mounts(db=db)
    except Exception as e:
        logger.error(f"Error during storage and mount audit: {e}")
    finally:
        db.close()

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
    
    # Run daily SRE log review (default 03:00 UTC, configurable via SRE_AUDIT_CRON_HOUR / SRE_AUDIT_CRON_MINUTE)
    audit_hour = int(os.getenv("SRE_AUDIT_CRON_HOUR", "3"))
    audit_minute = int(os.getenv("SRE_AUDIT_CRON_MINUTE", "0"))
    scheduler.add_job(run_daily_sre_audit, "cron", hour=audit_hour, minute=audit_minute)

    # Run proactive storage and FUSE mount health audits every 10 minutes
    scheduler.add_job(run_storage_mount_audit, "interval", minutes=10)

    scheduler.start()
    logger.info(f"Background Scheduler started (checking every 60s, heartbeat every {heartbeat_hours}h, SRE audit at {audit_hour:02d}:{audit_minute:02d} UTC, storage audits every 10m).")

