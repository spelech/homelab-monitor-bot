import logging
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, Incident, StackAudit
from app.stack_watcher import stack_watcher_manager

logger = logging.getLogger("StacksRouter")

router = APIRouter(prefix="/api/stacks", tags=["stacks"])

ACTIVE_STATUSES = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING", "BLOCKED"]


def serialize_audit(audit: Optional[StackAudit]) -> Optional[Dict[str, Any]]:
    if not audit:
        return None
    return {
        "id": audit.id,
        "stack_name": audit.stack_name,
        "status": audit.status,
        "summary": audit.summary,
        "error_count": str(audit.error_count),
        "containers_checked": str(audit.containers_checked),
        "created_at": audit.created_at.isoformat() if audit.created_at else None,
    }


def serialize_incident(inc: Optional[Incident]) -> Optional[Dict[str, Any]]:
    if not inc:
        return None
    return {
        "id": inc.id,
        "target_id": inc.target_id,
        "status": inc.status,
        "category": inc.category or "unknown",
        "stack_name": inc.stack_name,
        "origin": inc.origin or "reactive",
        "error_logs": inc.error_logs,
        "root_cause": inc.root_cause,
        "proposed_fix": inc.proposed_fix,
        "execution_log": inc.execution_log,
        "deferred_until": inc.deferred_until.isoformat() if inc.deferred_until else None,
        "completed_at": inc.completed_at.isoformat() if inc.completed_at else None,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
    }


@router.get("")
def list_stacks(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    Discover all Docker stacks on host, enriched with health status, container counts,
    pending image updates, last SRE audit result, and active incident counts.
    """
    stacks = stack_watcher_manager.discover_stacks()
    results = []

    for s in stacks:
        stack_name = s.get("name", "")
        working_dir = s.get("working_dir") or s.get("path") or ""
        config_files = s.get("config_files", "")
        status = s.get("status", "healthy")
        containers = s.get("containers", [])
        total_containers = s.get("total_containers", len(containers))
        running_containers = s.get("running_containers", 0)
        healthy_containers = s.get("healthy_containers", 0)
        unhealthy_containers = s.get("unhealthy_containers", 0)

        # Calculate updates_available_count
        updates_count = s.get("updates_available_count")
        if updates_count is None:
            updates_count = 0
            for c in containers:
                img = c.get("image", "")
                cached = stack_watcher_manager._update_cache.get(img)
                if cached and cached.get("update_available"):
                    updates_count += 1
                elif c.get("update_available"):
                    updates_count += 1

        # Fetch last StackAudit
        last_audit = s.get("last_audit")
        if last_audit is None:
            audit_rec = (
                db.query(StackAudit)
                .filter(StackAudit.stack_name == stack_name)
                .order_by(StackAudit.created_at.desc())
                .first()
            )
            if audit_rec:
                last_audit = serialize_audit(audit_rec)

        # Fetch active incidents count
        active_incidents_count = s.get("active_incidents_count")
        if active_incidents_count is None:
            active_incidents_count = (
                db.query(Incident)
                .filter(Incident.stack_name == stack_name, Incident.status.in_(ACTIVE_STATUSES))
                .count()
            )

        results.append({
            "name": stack_name,
            "path": working_dir,
            "working_dir": working_dir,
            "config_files": config_files,
            "status": status,
            "total_containers": total_containers,
            "running_containers": running_containers,
            "healthy_containers": healthy_containers,
            "unhealthy_containers": unhealthy_containers,
            "updates_available_count": updates_count,
            "active_incidents_count": active_incidents_count,
            "last_audit": last_audit,
            "containers": containers,
        })

    return results


@router.get("/{stack_name}")
def get_stack_detail(stack_name: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Get detailed inventory, containers, update status, and audit/incident history for a specific stack.
    """
    stack = stack_watcher_manager.get_stack_details(stack_name)
    if not stack:
        raise HTTPException(status_code=404, detail=f"Stack '{stack_name}' not found")

    containers = stack.get("containers", [])
    working_dir = stack.get("working_dir") or stack.get("path") or ""
    config_files = stack.get("config_files", "")
    status = stack.get("status", "healthy")
    total_containers = stack.get("total_containers", len(containers))
    running_containers = stack.get("running_containers", 0)
    healthy_containers = stack.get("healthy_containers", 0)
    unhealthy_containers = stack.get("unhealthy_containers", 0)

    # Enrich container list with cached update info
    enriched_containers = []
    updates_count = 0
    for c in containers:
        c_dict = dict(c)
        img = c_dict.get("image", "")
        cached = stack_watcher_manager._update_cache.get(img)
        if cached:
            c_dict["update_available"] = cached.get("update_available", False)
            c_dict["update_status"] = cached.get("status", "UNKNOWN")
            c_dict["remote_digest"] = cached.get("remote_digest")
        else:
            if "update_available" not in c_dict:
                c_dict["update_available"] = False
            if "update_status" not in c_dict:
                c_dict["update_status"] = "UNKNOWN"

        if c_dict.get("update_available"):
            updates_count += 1
        enriched_containers.append(c_dict)

    # Audits
    last_audit_rec = (
        db.query(StackAudit)
        .filter(StackAudit.stack_name == stack_name)
        .order_by(StackAudit.created_at.desc())
        .first()
    )
    last_audit = serialize_audit(last_audit_rec) if last_audit_rec else stack.get("last_audit")

    audit_history_recs = (
        db.query(StackAudit)
        .filter(StackAudit.stack_name == stack_name)
        .order_by(StackAudit.created_at.desc())
        .limit(10)
        .all()
    )
    audit_history = [serialize_audit(a) for a in audit_history_recs]

    # Incidents
    active_incidents_count = (
        db.query(Incident)
        .filter(Incident.stack_name == stack_name, Incident.status.in_(ACTIVE_STATUSES))
        .count()
    )
    incident_recs = (
        db.query(Incident)
        .filter(Incident.stack_name == stack_name)
        .order_by(Incident.created_at.desc())
        .limit(20)
        .all()
    )
    incidents = [serialize_incident(inc) for inc in incident_recs]

    return {
        "name": stack_name,
        "path": working_dir,
        "working_dir": working_dir,
        "config_files": config_files,
        "status": status,
        "total_containers": total_containers,
        "running_containers": running_containers,
        "healthy_containers": healthy_containers,
        "unhealthy_containers": unhealthy_containers,
        "updates_available_count": updates_count,
        "active_incidents_count": active_incidents_count,
        "containers": enriched_containers,
        "last_audit": last_audit,
        "audit_history": audit_history,
        "incidents": incidents,
    }


@router.post("/audit-all")
def audit_all_stacks() -> List[Dict[str, Any]]:
    """
    Triggers SRE log review across all discovered Docker Compose stacks.
    """
    results = stack_watcher_manager.audit_all_stacks()
    return results


@router.post("/{stack_name}/audit")
def audit_stack(stack_name: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Triggers on-demand SRE log audit for a specific stack.
    """
    result = stack_watcher_manager.audit_stack_logs(stack_name, db=db)
    return result


@router.post("/{stack_name}/check-updates")
def check_stack_updates(stack_name: str) -> Dict[str, Any]:
    """
    Triggers a fresh registry image update check for all containers in the stack.
    """
    result = stack_watcher_manager.check_stack_updates(stack_name)
    return result
