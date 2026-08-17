import re
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db, get_setting, set_setting, check_maintenance_status

logger = logging.getLogger("SettingsRouter")

router = APIRouter(prefix="/api", tags=["settings"])

class MaintenanceRequest(BaseModel):
    duration: str  # "15m", "30m", "1h", "2h", "12h", "indefinite", "resume"

class SettingsUpdate(BaseModel):
    silent_mode: bool | None = None
    autopilot: bool | None = None

@router.get("/settings")
def get_system_settings(db: Session = Depends(get_db)):
    is_active, reason = check_maintenance_status(db)
    return {
        "silent_mode": get_setting("silent_mode") == "true",
        "autopilot": get_setting("autopilot") == "true",
        "maintenance_mode": get_setting("maintenance_mode", "false"),
        "maintenance_active": is_active,
        "maintenance_reason": reason
    }

@router.post("/settings")
def update_system_settings(settings: SettingsUpdate):
    if settings.silent_mode is not None:
        set_setting("silent_mode", "true" if settings.silent_mode else "false")
    if settings.autopilot is not None:
        set_setting("autopilot", "true" if settings.autopilot else "false")
    return {"status": "success"}

@router.post("/maintenance")
def set_maintenance_mode(req: MaintenanceRequest, db: Session = Depends(get_db)):
    val = req.duration.lower().strip()
    if val == "resume":
        set_setting("maintenance_mode", "false")
        logger.info("Maintenance mode disabled manually.")
        return {"status": "success", "detail": "Monitoring resumed"}
    elif val == "indefinite":
        set_setting("maintenance_mode", "indefinite")
        logger.info("Maintenance mode enabled indefinitely.")
        return {"status": "success", "detail": "Monitoring paused indefinitely"}
    else:
        # Match timed duration, e.g. "15m", "30m", "1h", "2h"
        match = re.match(r'^(\d+)([mh])$', val)
        if not match:
            raise HTTPException(status_code=400, detail="Invalid duration format. Use '15m', '30m', '1h', '2h', '12h', 'indefinite', or 'resume'.")
        
        amount, unit = match.groups()
        amount = int(amount)
        if unit == 'm':
            expire_dt = datetime.utcnow() + timedelta(minutes=amount)
        else:
            expire_dt = datetime.utcnow() + timedelta(hours=amount)
        
        iso_str = expire_dt.isoformat() + "Z"
        set_setting("maintenance_mode", iso_str)
        logger.info(f"Maintenance mode enabled until {iso_str}.")
        return {"status": "success", "detail": f"Monitoring paused for {val}"}
