"""
tests/test_scheduler.py
~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for background scheduler jobs and re-notification triggers.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app.database import Incident, Target
from app.scheduler import check_deferred_and_ignored

@pytest.fixture(autouse=True)
def default_no_maintenance():
    with patch("app.database.check_maintenance_status", return_value=(False, "")):
        yield

def test_expired_ignores_cleared(db_session):
    # Setup an ignored target whose ignore period has expired
    expired_time = datetime.utcnow() - timedelta(minutes=5)
    target = Target(id="test-expired-target", type="docker", ignored_until=expired_time)
    db_session.add(target)
    db_session.commit()

    check_deferred_and_ignored()

    db_session.expire_all()
    target_db = db_session.query(Target).filter_by(id="test-expired-target").first()
    assert target_db.ignored_until is None

def test_future_ignores_preserved(db_session):
    # Setup an ignored target whose ignore period is in the future
    future_time = datetime.utcnow() + timedelta(hours=2)
    target = Target(id="test-future-target", type="docker", ignored_until=future_time)
    db_session.add(target)
    db_session.commit()

    check_deferred_and_ignored()

    db_session.expire_all()
    target_db = db_session.query(Target).filter_by(id="test-future-target").first()
    assert target_db.ignored_until == future_time

def test_deferred_incidents_retried(db_session):
    target = Target(id="test-deferred-target", type="docker")
    db_session.add(target)
    db_session.commit()

    # Setup a deferred incident whose deferral period has expired
    expired_time = datetime.utcnow() - timedelta(minutes=5)
    incident = Incident(
        id="inc-def-001",
        target_id="test-deferred-target",
        status="DEFERRED",
        deferred_until=expired_time
    )
    db_session.add(incident)
    db_session.commit()

    with patch("app.scheduler.send_incident_notification") as mock_notify:
        check_deferred_and_ignored()
        mock_notify.assert_called_once_with("inc-def-001")

    db_session.expire_all()
    inc_db = db_session.query(Incident).filter_by(id="inc-def-001").first()
    assert inc_db.status == "PENDING_USER"
    assert inc_db.deferred_until is None

def test_renotify_unresponded_incidents(db_session):
    target = Target(id="test-renotify-target", type="docker")
    db_session.add(target)
    db_session.commit()

    # 1. Setup a PENDING_USER incident created 2 hours ago with last_notified_at 2 hours ago
    two_hours_ago = datetime.utcnow() - timedelta(hours=2)
    incident = Incident(
        id="inc-renotify-001",
        target_id="test-renotify-target",
        status="PENDING_USER",
        created_at=two_hours_ago,
        last_notified_at=two_hours_ago
    )
    db_session.add(incident)
    db_session.commit()

    # 2. Setup a PENDING_USER incident created 10 minutes ago (should NOT trigger)
    ten_mins_ago = datetime.utcnow() - timedelta(minutes=10)
    incident_recent = Incident(
        id="inc-norenotify-002",
        target_id="test-renotify-target",
        status="PENDING_USER",
        created_at=ten_mins_ago,
        last_notified_at=ten_mins_ago
    )
    db_session.add(incident_recent)
    db_session.commit()

    with patch("app.scheduler.send_incident_notification") as mock_notify:
        check_deferred_and_ignored()
        # Should only trigger for the old one
        mock_notify.assert_called_once_with("inc-renotify-001")

def test_renotify_handles_null_last_notified_at(db_session):
    target = Target(id="test-renotify-null", type="docker")
    db_session.add(target)
    db_session.commit()

    # Setup an incident created 2 hours ago where last_notified_at is Null (e.g. from older schema)
    two_hours_ago = datetime.utcnow() - timedelta(hours=2)
    incident = Incident(
        id="inc-renotify-003",
        target_id="test-renotify-null",
        status="PENDING_USER",
        created_at=two_hours_ago,
        last_notified_at=None
    )
    db_session.add(incident)
    db_session.commit()

    with patch("app.scheduler.send_incident_notification") as mock_notify:
        check_deferred_and_ignored()
        mock_notify.assert_called_once_with("inc-renotify-003")

@patch("os.getenv")
@patch("subprocess.run")
@patch("threading.Thread")
def test_check_systemd_services_active(mock_thread, mock_run, mock_getenv, db_session):
    mock_getenv.return_value = "plexmediaserver,ssh"
    
    # Mock systemctl is-active to return active (exit code 0)
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_run.return_value = mock_res

    from app.scheduler import check_systemd_services
    check_systemd_services()

    # Verify no incidents created
    incidents = db_session.query(Incident).all()
    assert len(incidents) == 0

@patch("os.getenv")
@patch("subprocess.run")
@patch("threading.Thread")
def test_check_systemd_services_inactive(mock_thread, mock_run, mock_getenv, db_session):
    mock_getenv.return_value = "plexmediaserver"
    
    # First mock run checks is-active (failed, exit code 1)
    # Second mock run fetches logs
    mock_res_active = MagicMock()
    mock_res_active.returncode = 1
    
    mock_res_logs = MagicMock()
    mock_res_logs.stdout = "plexmediaserver.service failed with exit code 1"
    
    mock_run.side_effect = [mock_res_active, mock_res_logs]

    from app.scheduler import check_systemd_services
    check_systemd_services()

    # Verify target created as systemd
    target = db_session.query(Target).filter_by(id="plexmediaserver").first()
    assert target is not None
    assert target.type == "systemd"

    # Verify incident created
    incident = db_session.query(Incident).filter_by(target_id="plexmediaserver").first()
    assert incident is not None
    assert incident.status == "DETECTED"
    assert incident.error_logs == "plexmediaserver.service failed with exit code 1"

    # Verify thread started trigger_investigation
    mock_thread.assert_called_once()

@patch("app.database.check_maintenance_status")
@patch("subprocess.run")
def test_check_systemd_services_maintenance_bypassed(mock_run, mock_maint, db_session):
    mock_maint.return_value = (True, "Manual maintenance (indefinite)")
    from app.scheduler import check_systemd_services
    check_systemd_services()
    mock_run.assert_not_called()
    assert db_session.query(Incident).count() == 0

@patch("app.database.check_maintenance_status")
@patch("app.scheduler.send_incident_notification")
def test_check_deferred_and_ignored_maintenance_skips_renotify(mock_notify, mock_maint, db_session):
    mock_maint.return_value = (True, "Manual maintenance")
    target = Target(id="test-renotify-maint", type="docker")
    db_session.add(target)
    db_session.commit()

    two_hours_ago = datetime.utcnow() - timedelta(hours=2)
    incident = Incident(
        id="inc-renotify-maint-001",
        target_id="test-renotify-maint",
        status="PENDING_USER",
        created_at=two_hours_ago,
        last_notified_at=two_hours_ago
    )
    db_session.add(incident)
    db_session.commit()

    check_deferred_and_ignored()
    mock_notify.assert_not_called()


