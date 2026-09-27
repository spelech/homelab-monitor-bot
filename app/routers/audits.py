import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db, Incident, Target, StackAudit
from app.remediator import run_remediation

logger = logging.getLogger("AuditsRouter")

router = APIRouter(prefix="/api/audits", tags=["audits"])


class BulkActionRequest(BaseModel):
    action: str = Field(..., description="Action to perform: fix, defer, ignore, or dismiss")
    incident_ids: List[str] = Field(..., description="List of incident IDs to apply the action to")


def _format_date(dt: Any) -> str:
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d")
    return str(dt)[:10]


def _format_iso(dt: Any) -> Optional[str]:
    if not dt:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


@router.get("/daily")
def get_daily_audits(
    days: int = Query(30, ge=1, le=90, description="Number of days of audit reports to retrieve"),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Retrieves aggregated daily SRE audit reports for the last N days (default 30).
    Includes summary metrics (total stacks, clean, warning, outages) and
    actionable incident breakdowns with remediation state for each day.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)

    stack_audits = (
        db.query(StackAudit)
        .filter(StackAudit.created_at >= cutoff)
        .order_by(StackAudit.created_at.desc())
        .all()
    )

    incidents = (
        db.query(Incident)
        .filter(Incident.created_at >= cutoff)
        .order_by(Incident.created_at.desc())
        .all()
    )

    # Group stack audits by day
    audits_by_day: Dict[str, List[StackAudit]] = {}
    for audit in stack_audits:
        d_str = _format_date(audit.created_at)
        audits_by_day.setdefault(d_str, []).append(audit)

    # Group incidents by day
    incidents_by_day: Dict[str, List[Incident]] = {}
    for inc in incidents:
        d_str = _format_date(inc.created_at)
        incidents_by_day.setdefault(d_str, []).append(inc)

    # All unique dates from audits and incidents, sorted descending
    all_dates = sorted(set(list(audits_by_day.keys()) + list(incidents_by_day.keys())), reverse=True)

    results: List[Dict[str, Any]] = []
    for d_str in all_dates:
        day_audits = audits_by_day.get(d_str, [])
        day_incidents = incidents_by_day.get(d_str, [])

        healthy_count = sum(1 for a in day_audits if a.status == "HEALTHY")
        warning_count = sum(1 for a in day_audits if a.status == "WARNING")
        outages_count = sum(
            1 for a in day_audits if a.status in ("ACTION_REQUIRED", "OUTAGE", "DEGRADED", "ERROR")
        )

        serialized_audits = [
            {
                "id": a.id,
                "stack_name": a.stack_name,
                "status": a.status,
                "summary": a.summary,
                "error_count": str(a.error_count),
                "containers_checked": str(a.containers_checked),
                "created_at": _format_iso(a.created_at),
            }
            for a in day_audits
        ]

        actionable_items = [
            {
                "incident_id": inc.id,
                "target_id": inc.target_id,
                "stack_name": inc.stack_name,
                "status": inc.status,
                "category": inc.category or "unknown",
                "root_cause": inc.root_cause,
                "proposed_fix": inc.proposed_fix,
                "can_action": inc.status in ("PENDING_USER", "FAILED", "DEFERRED"),
                "created_at": _format_iso(inc.created_at),
                "deferred_until": _format_iso(inc.deferred_until),
            }
            for inc in day_incidents
        ]

        results.append({
            "date": d_str,
            "total_stacks": len(day_audits),
            "healthy_count": healthy_count,
            "warning_count": warning_count,
            "outages_count": outages_count,
            "stack_audits": serialized_audits,
            "actionable_items": actionable_items,
        })

    return results


@router.post("/actions/bulk")
def execute_bulk_incident_actions(
    payload: BulkActionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Executes a bulk action ('fix', 'defer', 'ignore', 'dismiss') across multiple incidents.
    """
    action = payload.action.lower().strip()
    valid_actions = {"fix", "defer", "ignore", "dismiss"}
    if action not in valid_actions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{payload.action}'. Allowed actions: {', '.join(sorted(valid_actions))}"
        )

    if not payload.incident_ids:
        return {"status": "ok", "processed": 0, "action": action, "incident_ids": []}

    incidents = db.query(Incident).filter(Incident.id.in_(payload.incident_ids)).all()
    now = datetime.utcnow()
    processed_ids = []

    for inc in incidents:
        if action == "fix":
            inc.status = "FIXING"
            background_tasks.add_task(run_remediation, inc.id)
            processed_ids.append(inc.id)

        elif action == "defer":
            inc.deferred_until = now + timedelta(hours=24)
            inc.status = "DEFERRED"
            processed_ids.append(inc.id)

        elif action == "ignore":
            target = db.query(Target).filter(Target.id == inc.target_id).first()
            if target:
                target.ignored_until = datetime(9999, 12, 31, 23, 59, 59)
            inc.status = "IGNORED"
            processed_ids.append(inc.id)

        elif action == "dismiss":
            inc.status = "RESOLVED"
            inc.completed_at = now
            inc.execution_log = "Dismissed manually via bulk action."
            processed_ids.append(inc.id)

    db.commit()

    return {
        "status": "ok",
        "processed": len(processed_ids),
        "action": action,
        "incident_ids": processed_ids,
    }
