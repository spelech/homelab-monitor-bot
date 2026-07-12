import os
import logging
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Query, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import init_db, get_db, Target, Incident
from app.watcher import start_watcher_thread
from app.scheduler import start_scheduler
from app.remediator import run_remediation

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AutoHeal")

# Load environment configs
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN")
if not WEBHOOK_TOKEN:
    raise ValueError("WEBHOOK_TOKEN environment variable must be set!")
PORT = int(os.getenv("PORT", "9013"))
HOST = os.getenv("HOST", "0.0.0.0")

# Setup templates
templates = Jinja2Templates(directory="/containers/monitorbot/app/templates")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    logger.info("Initializing AutoHeal Database...")
    init_db()
    
    logger.info("Starting Docker event watcher background worker...")
    start_watcher_thread()
    
    logger.info("Starting background APScheduler...")
    start_scheduler()
    
    logger.info("Starting Telegram updates listener...")
    from app.telegram_bot import start_telegram_listener
    start_telegram_listener()
    
    yield
    # Shutdown actions (if any)
    logger.info("Shutting down AutoHeal...")

app = FastAPI(title="AutoHeal Autonomous SRE", lifespan=lifespan)

class WebhookPayload(BaseModel):
    action: str  # fix, defer, ignore

@app.get("/", response_class=HTMLResponse)
def get_dashboard(request: Request, db: Session = Depends(get_db)):
    # 1. Fetch counts
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING"]
    active_count = db.query(Incident).filter(Incident.status.in_(active_statuses)).count()
    resolved_count = db.query(Incident).filter(Incident.status == "RESOLVED").count()
    targets_count = db.query(Target).count()
    
    now = datetime.utcnow()
    ignored_count = db.query(Target).filter(
        Target.ignored_until.is_not(None),
        Target.ignored_until > now
    ).count()

    # 2. Fetch records
    active_incidents = db.query(Incident).filter(
        Incident.status.in_(active_statuses)
    ).order_by(Incident.created_at.desc()).all()

    ignored_targets = db.query(Target).filter(
        Target.ignored_until.is_not(None),
        Target.ignored_until > now
    ).all()

    history_incidents = db.query(Incident).filter(
        Incident.status.notin_(active_statuses)
    ).order_by(Incident.created_at.desc()).limit(100).all()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "active_count": active_count,
        "resolved_count": resolved_count,
        "targets_count": targets_count,
        "ignored_count": ignored_count,
        "active_incidents": active_incidents,
        "ignored_targets": ignored_targets,
        "history_incidents": history_incidents,
        "token": WEBHOOK_TOKEN
    })

@app.post("/api/webhooks/{incident_id}")
async def handle_webhook(
    incident_id: str,
    payload: WebhookPayload,
    background_tasks: BackgroundTasks,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    # 1. Authenticate secret token
    if token != WEBHOOK_TOKEN:
        logger.warning(f"Unauthorized webhook trigger attempt. Token: {token}")
        raise HTTPException(status_code=401, detail="Invalid auth token")

    # 2. Query incident
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # 3. Idempotency Check
    action = payload.action.lower()
    if incident.status in ["FIXING", "RESOLVED", "DEFERRED", "IGNORED"]:
        logger.info(f"Incident {incident_id} already in status {incident.status}. Webhook ignored (duplicate hit).")
        return {"status": "ok", "detail": f"Already processed in state {incident.status}"}

    # 4. Handle actions
    now = datetime.utcnow()
    if action == "defer":
        logger.info(f"Deferring incident {incident_id} by 24 hours.")
        incident.deferred_until = now + timedelta(hours=24)
        incident.status = "DEFERRED"
        db.commit()
        return {"status": "ok", "detail": "Incident deferred for 24h"}

    elif action == "ignore":
        logger.info(f"Ignoring target '{incident.target_id}' for 24 hours.")
        target = db.query(Target).filter(Target.id == incident.target_id).first()
        if target:
            target.ignored_until = now + timedelta(hours=24)
        incident.status = "IGNORED"
        db.commit()
        return {"status": "ok", "detail": f"Target {incident.target_id} ignored for 24h"}

    elif action == "fix":
        logger.info(f"Approved fix for incident {incident_id}. Spawning remediation worker...")
        incident.status = "FIXING"
        db.commit()
        # Spawn remediation async worker task in the background
        background_tasks.add_task(run_remediation, incident_id)
        return {"status": "ok", "detail": "Remediation triggered"}

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")

@app.post("/api/targets/{target_id}/unignore")
def unignore_target(target_id: str, db: Session = Depends(get_db)):
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    
    target.ignored_until = None
    db.commit()
    logger.info(f"Manually unignored target '{target_id}' via API.")
    return {"status": "ok", "detail": "Target unignored"}

@app.get("/api/incidents/active")
def get_active_incidents(db: Session = Depends(get_db)):
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING"]
    incidents = db.query(Incident).filter(Incident.status.in_(active_statuses)).all()
    return incidents

@app.get("/api/incidents/history")
def get_history_incidents(db: Session = Depends(get_db)):
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING"]
    incidents = db.query(Incident).filter(Incident.status.notin_(active_statuses)).all()
    return incidents
