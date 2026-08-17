import json
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, UpgradeRun
from app.upgrades import upgrades_manager

logger = logging.getLogger("UpgradesRouter")

router = APIRouter(prefix="/api/upgrades", tags=["upgrades"])

class UpgradeRunRequest(BaseModel):
    targets: Optional[List[str]] = None  # ["all"] or list of stack names

@router.get("/stacks")
def get_available_stacks():
    """Discover all manageable Docker compose stacks on the host."""
    stacks = upgrades_manager.discover_stacks()
    return stacks

@router.post("/run")
def trigger_upgrade(req: UpgradeRunRequest):
    """Trigger an asynchronous upgrade run."""
    res = upgrades_manager.start_upgrade(req.targets)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res

@router.get("/live")
def get_live_upgrade_status():
    """Poll live state and streaming logs of the currently running or most recent upgrade."""
    status = upgrades_manager.get_live_status()
    if not status:
        return {"status": "IDLE", "job": None}
    return {"status": status.get("status"), "job": status}

@router.post("/cancel")
def cancel_upgrade():
    """Request cancellation of the active upgrade."""
    res = upgrades_manager.cancel_active_upgrade()
    return res

@router.post("/canary")
def run_canary_audit_now():
    """Trigger an immediate standalone 4-phase Canary Health & Routing Audit."""
    results = upgrades_manager.run_canary_audit()
    return results

@router.get("/runs")
def list_upgrade_runs(limit: int = 20, db: Session = Depends(get_db)):
    """Retrieve historical upgrade executions."""
    runs = db.query(UpgradeRun).order_by(UpgradeRun.started_at.desc()).limit(limit).all()
    results = []
    for r in runs:
        try:
            targets_list = json.loads(r.targets) if r.targets else []
        except Exception:
            targets_list = [r.targets]
            
        try:
            canary_obj = json.loads(r.canary_results) if r.canary_results else {}
        except Exception:
            canary_obj = {}

        results.append({
            "id": r.id,
            "status": r.status,
            "targets": targets_list,
            "canary_results": canary_obj,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None
        })
    return results

@router.get("/runs/{run_id}")
def get_upgrade_run_detail(run_id: str, db: Session = Depends(get_db)):
    """Get full details and logs for a specific upgrade run."""
    r = db.query(UpgradeRun).filter(UpgradeRun.id == run_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Upgrade run not found")
        
    try:
        targets_list = json.loads(r.targets) if r.targets else []
    except Exception:
        targets_list = [r.targets]
        
    try:
        canary_obj = json.loads(r.canary_results) if r.canary_results else {}
    except Exception:
        canary_obj = {}

    return {
        "id": r.id,
        "status": r.status,
        "targets": targets_list,
        "logs": r.logs or "",
        "canary_results": canary_obj,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None
    }
