import os
import logging
from typing import List, Optional
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, Incident, Target, get_setting, check_maintenance_status
from app.remediator import run_remediation
from app.notifier import send_followup_notification
from app.qdrant_mem import qdrant_mem

logger = logging.getLogger("IncidentsRouter")

router = APIRouter(prefix="/api", tags=["incidents"])

WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")

class WebhookPayload(BaseModel):
    action: str  # fix, defer, ignore

class IncidentActionRequest(BaseModel):
    action: str  # fix, defer, ignore

@router.get("/incidents/active")
def get_active_incidents(db: Session = Depends(get_db)):
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING", "BLOCKED"]
    incidents = db.query(Incident).filter(Incident.status.in_(active_statuses)).order_by(Incident.created_at.desc()).all()
    return [{
        "id": inc.id,
        "target_id": inc.target_id,
        "status": inc.status,
        "category": inc.category or "unknown",
        "error_logs": inc.error_logs,
        "root_cause": inc.root_cause,
        "proposed_fix": inc.proposed_fix,
        "execution_log": inc.execution_log,
        "deferred_until": inc.deferred_until.isoformat() if inc.deferred_until else None,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "completed_at": inc.completed_at.isoformat() if inc.completed_at else None
    } for inc in incidents]

@router.get("/incidents/history")
def get_history_incidents(limit: int = 100, db: Session = Depends(get_db)):
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING", "BLOCKED"]
    incidents = db.query(Incident).filter(Incident.status.notin_(active_statuses)).order_by(Incident.created_at.desc()).limit(limit).all()
    return [{
        "id": inc.id,
        "target_id": inc.target_id,
        "status": inc.status,
        "category": inc.category or "unknown",
        "error_logs": inc.error_logs,
        "root_cause": inc.root_cause,
        "proposed_fix": inc.proposed_fix,
        "execution_log": inc.execution_log,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "completed_at": inc.completed_at.isoformat() if inc.completed_at else None
    } for inc in incidents]

@router.get("/incidents/search")
def search_incidents(q: str = Query(...), limit: int = 10, db: Session = Depends(get_db)):
    matches = qdrant_mem.semantic_search(q, limit=limit)
    if not matches:
        return []
    
    incident_ids = [match.id for match in matches]
    incidents = db.query(Incident).filter(Incident.id.in_(incident_ids)).all()
    
    id_to_score = {match.id: match.score for match in matches}
    sorted_incidents = sorted(incidents, key=lambda x: id_to_score.get(x.id, 0), reverse=True)
    
    results = []
    for inc in sorted_incidents:
        results.append({
            "id": inc.id,
            "target_id": inc.target_id,
            "status": inc.status,
            "category": inc.category or "unknown",
            "root_cause": inc.root_cause,
            "proposed_fix": inc.proposed_fix,
            "completed_at": inc.completed_at.isoformat() if inc.completed_at else None,
            "score": round(id_to_score.get(inc.id, 0), 4)
        })
    return results

@router.post("/incidents/{incident_id}/action")
def trigger_incident_action(
    incident_id: str,
    req: IncidentActionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    action = req.action.lower()
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    now = datetime.utcnow()
    if action == "defer":
        incident.deferred_until = now + timedelta(hours=24)
        incident.status = "DEFERRED"
        db.commit()
        return {"status": "ok", "detail": "Incident deferred for 24h"}

    elif action == "ignore":
        target = db.query(Target).filter(Target.id == incident.target_id).first()
        if target:
            target.ignored_until = datetime(9999, 12, 31, 23, 59, 59)
        incident.status = "IGNORED"
        db.commit()
        return {"status": "ok", "detail": f"Target {incident.target_id} permanently ignored"}

    elif action == "fix":
        incident.status = "FIXING"
        db.commit()
        background_tasks.add_task(run_remediation, incident_id)
        return {"status": "ok", "detail": "Remediation triggered"}

    elif action == "dismiss":
        incident.status = "RESOLVED"
        incident.completed_at = now
        incident.execution_log = "Dismissed manually from dashboard."
        db.commit()
        return {"status": "ok", "detail": "Incident dismissed"}

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")

@router.get("/targets")
def list_targets(db: Session = Depends(get_db)):
    targets = db.query(Target).all()
    now = datetime.utcnow()
    
    # Try getting live docker container states
    running_map = {}
    try:
        import docker
        client = docker.from_env()
        for c in client.containers.list(all=True):
            running_map[c.name] = {
                "status": c.status,
                "health": c.attrs.get("State", {}).get("Health", {}).get("Status", "none")
            }
    except Exception:
        pass

    result = []
    for t in targets:
        is_ignored = bool(t.ignored_until and t.ignored_until > now)
        info = running_map.get(t.id, {"status": "unknown", "health": "unknown"})
        result.append({
            "id": t.id,
            "type": t.type,
            "is_ignored": is_ignored,
            "ignored_until": t.ignored_until.isoformat() if t.ignored_until else None,
            "docker_status": info["status"],
            "docker_health": info["health"]
        })
    return result

@router.post("/targets/{target_id}/unignore")
def unignore_target(target_id: str, db: Session = Depends(get_db)):
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    
    target.ignored_until = None
    db.commit()
    return {"status": "ok", "detail": "Target unignored"}

# Backwards compatible webhook endpoint for ntfy action buttons
@router.api_route("/webhooks/{incident_id}", methods=["GET", "POST"])
async def handle_webhook(
    incident_id: str,
    background_tasks: BackgroundTasks,
    payload: Optional[WebhookPayload] = None,
    action: Optional[str] = Query(None),
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    act = (payload.action if payload else action) or action
    if not act:
        raise HTTPException(status_code=400, detail="Action parameter required")

    expected_token = os.getenv("WEBHOOK_TOKEN", "")
    if token != expected_token:
        logger.warning(f"Unauthorized webhook attempt with token: {token}")
        raise HTTPException(status_code=401, detail="Invalid auth token")

    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    action_name = act.lower()
    if incident.status in ["FIXING", "RESOLVED", "DEFERRED", "IGNORED"]:
        return {"status": "ok", "detail": f"Already processed in state {incident.status}"}

    # Pre-check health
    target_id = incident.target_id
    already_healthy = False
    chk_detail = ""
    try:
        target = db.query(Target).filter(Target.id == target_id).first()
        if target and target.type == "systemd":
            import subprocess
            res = subprocess.run(["systemctl", "is-active", "--quiet", target_id])
            if res.returncode == 0:
                already_healthy = True
                chk_detail = "active (running)"
        else:
            import docker
            client = docker.from_env()
            container = client.containers.get(target_id)
            state = container.attrs.get("State", {})
            running = state.get("Running", False)
            health = state.get("Health", {}).get("Status", "none")
            if running and health in ["none", "healthy"]:
                already_healthy = True
                chk_detail = f"running (health: {health})"
    except Exception as e:
        logger.warning(f"Webhook health precheck failed: {e}")

    if already_healthy:
        incident.status = "RESOLVED"
        incident.completed_at = datetime.utcnow()
        incident.execution_log = f"Incident resolved automatically: Target was already healthy ({chk_detail}) when user interacted with notification."
        db.commit()
        msg = f"Container '{target_id}' was verified healthy ({chk_detail}) and resolved automatically without action."
        import app.main as main_mod
        if hasattr(main_mod, "send_followup_notification"):
            main_mod.send_followup_notification(incident_id, msg, success=True)
        else:
            send_followup_notification(incident_id, msg, success=True)
        return {"status": "ok", "detail": f"Incident was already resolved without action ({chk_detail})"}

    now = datetime.utcnow()
    if action_name == "defer":
        incident.deferred_until = now + timedelta(hours=24)
        incident.status = "DEFERRED"
        db.commit()
        return {"status": "ok", "detail": "Incident deferred for 24h"}

    elif action_name == "ignore":
        target = db.query(Target).filter(Target.id == incident.target_id).first()
        if target:
            target.ignored_until = datetime(9999, 12, 31, 23, 59, 59)
        incident.status = "IGNORED"
        db.commit()
        return {"status": "ok", "detail": f"Target {incident.target_id} permanently ignored"}

    elif action_name == "fix":
        incident.status = "FIXING"
        db.commit()
        import app.main as main_mod
        remedy_fn = getattr(main_mod, "run_remediation", run_remediation)
        background_tasks.add_task(remedy_fn, incident_id)
        return {"status": "ok", "detail": "Remediation triggered"}

    raise HTTPException(status_code=400, detail=f"Unknown action '{action_name}'")


@router.get("/incidents/{incident_id}/transcript")
def get_incident_transcript(incident_id: str, db: Session = Depends(get_db)):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    from app.transcript_logger import get_transcript
    events = get_transcript(incident_id)
    return {
        "incident_id": incident_id,
        "target_id": incident.target_id,
        "events": events
    }

