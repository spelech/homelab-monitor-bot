import os
import pytest
import concurrent.futures
from unittest.mock import patch, MagicMock
from app.system_health import probe_mount, audit_storage_and_mounts, get_monitored_mounts, check_system_resources
from app.scheduler import run_storage_mount_audit
from app.database import Incident, Target, SystemSetting
from datetime import datetime, timedelta

def test_probe_healthy_mount():
    with patch("os.statvfs") as mock_stat:
        mock_stat.return_value = MagicMock(f_bavail=1000000, f_blocks=2000000, f_bfree=1000000, f_frsize=4096)
        res = probe_mount("/drives/movies1")
        assert res["healthy"] is True
        assert res["error"] is None
        assert res["path"] == "/drives/movies1"
        assert res["usage_percent"] == 50.0

def test_probe_enotconn_mount():
    with patch("os.statvfs", side_effect=OSError(107, "Transport endpoint is not connected")):
        res = probe_mount("/drives/moviestv3/riven/mount")
        assert res["healthy"] is False
        assert res["errno"] == 107
        assert "Transport endpoint is not connected" in res["error"]

def test_probe_mount_timeout():
    def hanging_stat(*args, **kwargs):
        import time
        time.sleep(2)
        return MagicMock()

    with patch("os.statvfs", side_effect=hanging_stat):
        res = probe_mount("/drives/stale_mount", timeout=0.1)
        assert res["healthy"] is False
        assert res["errno"] == 110
        assert "timed out" in res["error"]

def test_get_monitored_mounts_env():
    with patch.dict("os.environ", {"MONITORED_MOUNTS": "/mnt/custom1, /mnt/custom2"}):
        mounts = get_monitored_mounts()
        assert "/mnt/custom1" in mounts
        assert "/mnt/custom2" in mounts

def test_get_monitored_mounts_discovery():
    with patch.dict("os.environ", {}, clear=False):
        if "MONITORED_MOUNTS" in os.environ:
            del os.environ["MONITORED_MOUNTS"]
        mounts = get_monitored_mounts()
        assert isinstance(mounts, list)
        assert len(mounts) > 0
        assert "/" in mounts

def test_check_system_resources():
    meminfo_content = """MemTotal:       32615916 kB
MemFree:         5000000 kB
MemAvailable:   13519344 kB
SwapTotal:      67108860 kB
SwapFree:       39780604 kB
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=meminfo_content.splitlines()), __exit__=MagicMock()))):
            res = check_system_resources()
            assert res["healthy"] is True
            assert res["memory"]["total_mb"] == 32615916 // 1024
            assert res["swap"]["total_mb"] == 67108860 // 1024

def test_check_system_resources_high_usage():
    meminfo_content = """MemTotal:       10000000 kB
MemFree:          100000 kB
MemAvailable:     200000 kB
SwapTotal:      10000000 kB
SwapFree:         500000 kB
"""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=MagicMock(return_value=meminfo_content.splitlines()), __exit__=MagicMock()))):
            res = check_system_resources()
            assert res["healthy"] is False
            assert len(res["warnings"]) >= 1

def test_audit_creates_mount_incident(db_session):
    with patch("app.system_health.get_monitored_mounts", return_value=["/drives/moviestv3/riven/mount"]):
        with patch("app.system_health.probe_mount", return_value={
            "path": "/drives/moviestv3/riven/mount",
            "healthy": False,
            "errno": 107,
            "error": "Transport endpoint is not connected"
        }):
            with patch("app.notifier.send_incident_notification"):
                audit_storage_and_mounts(db=db_session)

    inc = db_session.query(Incident).filter(Incident.target_id == "mount:/drives/moviestv3/riven/mount").first()
    assert inc is not None
    assert inc.category == "storage_mount"
    assert "fusermount -u -z" in inc.proposed_fix

    target = db_session.query(Target).filter(Target.id == "mount:/drives/moviestv3/riven/mount").first()
    assert target is not None
    assert target.type == "system_mount"

def test_audit_skips_when_ignored(db_session):
    target_id = "mount:/drives/ignored_mount"
    target = Target(id=target_id, type="system_mount", ignored_until=datetime.utcnow() + timedelta(hours=2))
    db_session.add(target)
    db_session.commit()

    with patch("app.system_health.get_monitored_mounts", return_value=["/drives/ignored_mount"]):
        with patch("app.system_health.probe_mount", return_value={
            "path": "/drives/ignored_mount",
            "healthy": False,
            "errno": 107,
            "error": "Transport endpoint is not connected"
        }):
            with patch("app.notifier.send_incident_notification"):
                audit_storage_and_mounts(db=db_session)

    inc = db_session.query(Incident).filter(Incident.target_id == target_id).first()
    assert inc is None

def test_audit_skips_duplicate_active_incident(db_session):
    target_id = "mount:/drives/moviestv3/riven/mount"
    target = Target(id=target_id, type="system_mount")
    db_session.add(target)
    existing_inc = Incident(
        id="existing-123",
        target_id=target_id,
        status="PENDING_USER",
        category="storage_mount",
        error_logs="Previous error"
    )
    db_session.add(existing_inc)
    db_session.commit()

    with patch("app.system_health.get_monitored_mounts", return_value=["/drives/moviestv3/riven/mount"]):
        with patch("app.system_health.probe_mount", return_value={
            "path": "/drives/moviestv3/riven/mount",
            "healthy": False,
            "errno": 107,
            "error": "Transport endpoint is not connected"
        }):
            with patch("app.notifier.send_incident_notification"):
                audit_storage_and_mounts(db=db_session)

    inc_count = db_session.query(Incident).filter(Incident.target_id == target_id).count()
    assert inc_count == 1

def test_audit_circuit_breaker_tripping(db_session):
    target_id = "mount:/drives/broken_mount"
    target = Target(id=target_id, type="system_mount")
    db_session.add(target)

    # Add two recently failed incidents
    f1 = Incident(
        id="f1",
        target_id=target_id,
        status="FAILED",
        completed_at=datetime.utcnow() - timedelta(minutes=10)
    )
    f2 = Incident(
        id="f2",
        target_id=target_id,
        status="FAILED",
        completed_at=datetime.utcnow() - timedelta(minutes=5)
    )
    db_session.add(f1)
    db_session.add(f2)
    db_session.commit()

    with patch("app.system_health.get_monitored_mounts", return_value=["/drives/broken_mount"]):
        with patch("app.system_health.probe_mount", return_value={
            "path": "/drives/broken_mount",
            "healthy": False,
            "errno": 107,
            "error": "Transport endpoint is not connected"
        }):
            with patch("app.notifier.send_incident_notification"):
                audit_storage_and_mounts(db=db_session)

    blocked_inc = db_session.query(Incident).filter(
        Incident.target_id == target_id,
        Incident.status == "BLOCKED"
    ).first()
    assert blocked_inc is not None
    assert "Circuit breaker tripped" in blocked_inc.error_logs

def test_scheduler_storage_audit_skips_in_maintenance_mode(db_session):
    with patch("app.database.check_maintenance_status", return_value=(True, "Maintenance active")):
        with patch("app.system_health.audit_storage_and_mounts") as mock_audit:
            run_storage_mount_audit()
            mock_audit.assert_not_called()
