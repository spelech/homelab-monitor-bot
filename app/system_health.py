import os
import glob
import uuid
import logging
import concurrent.futures
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.database import SessionLocal, Target, Incident
from app.notifier import send_incident_notification

logger = logging.getLogger("SystemHealth")


def probe_mount(mount_path: str, timeout: float = 3.0) -> Dict[str, Any]:
    """
    Probes a mount point path in an isolated worker thread with a strict timeout.
    Returns health status, utilization metrics, or detailed OS/timeout errors.
    """
    def _do_stat() -> Dict[str, Any]:
        stat = os.statvfs(mount_path)
        total_bytes = stat.f_blocks * stat.f_frsize
        free_bytes = stat.f_bavail * stat.f_frsize
        used_bytes = total_bytes - (stat.f_bfree * stat.f_frsize)
        usage_pct = (used_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
        return {
            "path": mount_path,
            "healthy": True,
            "total_bytes": total_bytes,
            "free_bytes": free_bytes,
            "used_bytes": used_bytes,
            "usage_percent": round(usage_pct, 2),
            "error": None,
            "errno": None,
        }

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_do_stat)
    try:
        res = future.result(timeout=timeout)
        executor.shutdown(wait=False)
        return res
    except (concurrent.futures.TimeoutError, TimeoutError):
        executor.shutdown(wait=False)
        return {
            "path": mount_path,
            "healthy": False,
            "errno": 110,
            "error": f"Probe timed out after {timeout}s (unresponsive/hung mount)",
            "usage_percent": None,
        }
    except OSError as e:
        executor.shutdown(wait=False)
        return {
            "path": mount_path,
            "healthy": False,
            "errno": e.errno,
            "error": str(e),
            "usage_percent": None,
        }
    except Exception as e:
        executor.shutdown(wait=False)
        return {
            "path": mount_path,
            "healthy": False,
            "errno": getattr(e, "errno", None),
            "error": str(e),
            "usage_percent": None,
        }


def get_monitored_mounts() -> List[str]:
    """
    Discovers active storage drives and FUSE mount paths to monitor.
    Uses MONITORED_MOUNTS if configured, otherwise inspects /proc/mounts and filesystem conventions.
    """
    env_mounts = os.getenv("MONITORED_MOUNTS", "").strip()
    if env_mounts:
        return [m.strip() for m in env_mounts.split(",") if m.strip()]

    mounts: List[str] = []

    # 1. Inspect /proc/mounts for host and FUSE mounts
    if os.path.exists("/proc/mounts"):
        try:
            with open("/proc/mounts", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3:
                        mount_point, fstype = parts[1], parts[2]
                        if mount_point.startswith("/run/user") or mount_point.startswith("/sys") or mount_point.startswith("/proc"):
                            continue
                        if mount_point.startswith("/drives/") or mount_point.startswith("/mnt/"):
                            mounts.append(mount_point)
                        elif fstype.startswith("fuse") or fstype in ["fuseblk", "rclone", "mergerfs", "nfs", "cifs"]:
                            mounts.append(mount_point)
        except Exception as e:
            logger.warning(f"Failed to parse /proc/mounts: {e}")

    # 2. Add standard static mount locations
    for standard_path in ["/", "/dev/shm", "/tmp/cache", "/mnt/gdrive"]:
        if os.path.exists(standard_path) and standard_path not in mounts:
            mounts.append(standard_path)

    # 3. Add drives folder contents
    for d in glob.glob("/drives/*"):
        if d not in mounts:
            mounts.append(d)

    # Return deduplicated list while preserving discovery order
    return list(dict.fromkeys(mounts))


def check_system_resources() -> Dict[str, Any]:
    """
    Inspects host memory and swap utilization via /proc/meminfo.
    Returns memory and swap metrics with health warnings if thresholds are breached.
    """
    try:
        meminfo: Dict[str, int] = {}
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = parts[1].strip().split()[0]
                        meminfo[k] = int(v)

        mem_total_kb = meminfo.get("MemTotal", 0)
        mem_avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        mem_used_kb = mem_total_kb - mem_avail_kb
        mem_percent = (mem_used_kb / mem_total_kb * 100.0) if mem_total_kb > 0 else 0.0

        swap_total_kb = meminfo.get("SwapTotal", 0)
        swap_free_kb = meminfo.get("SwapFree", 0)
        swap_used_kb = swap_total_kb - swap_free_kb
        swap_percent = (swap_used_kb / swap_total_kb * 100.0) if swap_total_kb > 0 else 0.0

        healthy = True
        warnings: List[str] = []
        if mem_total_kb > 0 and mem_percent > 95.0:
            healthy = False
            warnings.append(f"High RAM usage: {mem_percent:.1f}% used ({mem_used_kb // 1024}MB / {mem_total_kb // 1024}MB)")
        if swap_total_kb > 0 and swap_percent > 90.0:
            healthy = False
            warnings.append(f"High swap usage: {swap_percent:.1f}% used ({swap_used_kb // 1024}MB / {swap_total_kb // 1024}MB)")

        return {
            "healthy": healthy,
            "memory": {
                "total_mb": mem_total_kb // 1024,
                "available_mb": mem_avail_kb // 1024,
                "used_mb": mem_used_kb // 1024,
                "percent": round(mem_percent, 1),
            },
            "swap": {
                "total_mb": swap_total_kb // 1024,
                "free_mb": swap_free_kb // 1024,
                "used_mb": swap_used_kb // 1024,
                "percent": round(swap_percent, 1),
            },
            "warnings": warnings,
            "error": "; ".join(warnings) if warnings else None,
        }
    except Exception as e:
        logger.error(f"Failed to check system resources: {e}")
        return {
            "healthy": False,
            "memory": {},
            "swap": {},
            "warnings": [str(e)],
            "error": str(e),
        }


def audit_storage_and_mounts(db: Optional[Session] = None) -> List[Dict[str, Any]]:
    """
    Audits all monitored storage drives and FUSE mounts for responsiveness,
    transport disconnections (ENOTCONN), and hung states.
    Automatically creates incidents with remediation commands when broken mounts are detected.
    """
    db_provided = db is not None
    session = db if db_provided else SessionLocal()

    try:
        mount_paths = get_monitored_mounts()
        results: List[Dict[str, Any]] = []

        for mount_path in mount_paths:
            res = probe_mount(mount_path, timeout=3.0)
            results.append(res)

            if not res.get("healthy", False):
                target_id = f"mount:{mount_path}"
                logger.warning(f"Mount health probe failed for '{mount_path}': {res.get('error')}")

                # Ensure Target exists
                target = session.query(Target).filter(Target.id == target_id).first()
                if not target:
                    target = Target(id=target_id, type="system_mount", ignored_until=None)
                    session.add(target)
                    session.commit()
                    session.refresh(target)

                # Skip if target is temporarily ignored
                if target.ignored_until and target.ignored_until > datetime.utcnow():
                    logger.info(f"Target '{target_id}' is currently ignored until {target.ignored_until}. Skipping incident.")
                    continue

                # Skip if an active incident already exists
                active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING", "BLOCKED"]
                active_inc = session.query(Incident).filter(
                    Incident.target_id == target_id,
                    Incident.status.in_(active_statuses),
                ).first()
                if active_inc:
                    logger.info(f"Active incident {active_inc.id} already exists for target '{target_id}'. Skipping duplicate.")
                    continue

                # Check circuit breaker: 2+ failures in the last 60 minutes
                one_hour_ago = datetime.utcnow() - timedelta(minutes=60)
                recent_failures = session.query(Incident).filter(
                    Incident.target_id == target_id,
                    Incident.status == "FAILED",
                    Incident.completed_at >= one_hour_ago,
                ).count()

                incident_id = str(uuid.uuid4())
                if recent_failures >= 2:
                    logger.warning(f"Circuit breaker tripped for mount '{mount_path}': {recent_failures} failures in the last 60 minutes.")
                    incident = Incident(
                        id=incident_id,
                        target_id=target_id,
                        status="BLOCKED",
                        category="storage_mount",
                        error_logs=f"Circuit breaker tripped: {recent_failures} failures in the last 60 minutes. Mount probe error:\n{res.get('error')}",
                        root_cause=f"Repeated storage mount failure for '{mount_path}'. Automatic recovery paused.",
                        proposed_fix=f"fusermount -u -z '{mount_path}' || umount -l '{mount_path}'\n# Manual triage required.",
                        origin="storage_audit",
                        created_at=datetime.utcnow(),
                        completed_at=datetime.utcnow(),
                    )
                else:
                    if "riven" in mount_path:
                        proposed_fix = (
                            f"fusermount -u -z '{mount_path}' || umount -l '{mount_path}'\n"
                            f"docker start riven 2>/dev/null || docker compose -f /containers/media_content/docker-compose.yaml up -d riven || true"
                        )
                    else:
                        proposed_fix = (
                            f"fusermount -u -z '{mount_path}' || umount -l '{mount_path}'\n"
                            f"# Remount or restart provider service if applicable\n"
                            f"# systemctl restart rclone || docker compose restart"
                        )
                    root_cause = (
                        f"Storage mount '{mount_path}' is unresponsive or transport endpoint is disconnected.\n"
                        f"Error: {res.get('error')}"
                    )
                    incident = Incident(
                        id=incident_id,
                        target_id=target_id,
                        status="PENDING_USER",
                        category="storage_mount",
                        error_logs=f"Storage mount probe failure on {mount_path}:\n{res.get('error')}",
                        root_cause=root_cause,
                        proposed_fix=proposed_fix,
                        origin="storage_audit",
                        created_at=datetime.utcnow(),
                    )

                session.add(incident)
                session.commit()
                logger.info(f"Created mount incident {incident_id} for target '{target_id}'.")

                try:
                    send_incident_notification(incident_id)
                except Exception as notify_err:
                    logger.error(f"Failed to send notification for mount incident {incident_id}: {notify_err}")

        return results
    finally:
        if not db_provided:
            session.close()
