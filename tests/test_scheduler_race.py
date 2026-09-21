import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from app.database import Incident, Target
from app.scheduler import check_deferred_and_ignored

@pytest.fixture(autouse=True)
def default_no_maintenance():
    with patch("app.database.check_maintenance_status", return_value=(False, "")):
        yield

def test_sre_audit_incident_not_auto_resolved_prematurely(db_session):
    # Incident created by sre_daily_audit should not be resolved 30 seconds later
    inc = Incident(
        id="test-audit-inc-1",
        target_id="prowlarr",
        status="PENDING_USER",
        origin="sre_daily_audit",
        root_cause="Stale endpoint config",
        proposed_fix="docker compose restart prowlarr",
        created_at=datetime.utcnow() - timedelta(seconds=30)
    )
    db_session.add(inc)
    db_session.commit()

    docker_mock = MagicMock()
    container_mock = MagicMock()
    container_mock.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
    docker_mock.containers.get.return_value = container_mock

    with patch("docker.from_env", return_value=docker_mock):
        check_deferred_and_ignored()

    refreshed = db_session.query(Incident).filter(Incident.id == "test-audit-inc-1").first()
    # It should not have been auto-resolved instantly
    assert refreshed.status == "PENDING_USER"

def test_sre_audit_incident_not_resolved_even_after_grace_window(db_session):
    # SRE audit incidents should not be auto-resolved simply because container is running, even after 10 minutes
    inc = Incident(
        id="test-audit-inc-2",
        target_id="radarr",
        status="PENDING_USER",
        origin="sre_daily_audit",
        root_cause="Database lock contention",
        proposed_fix="docker compose restart radarr",
        created_at=datetime.utcnow() - timedelta(minutes=10)
    )
    db_session.add(inc)
    db_session.commit()

    docker_mock = MagicMock()
    container_mock = MagicMock()
    container_mock.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
    docker_mock.containers.get.return_value = container_mock

    with patch("docker.from_env", return_value=docker_mock):
        check_deferred_and_ignored()

    refreshed = db_session.query(Incident).filter(Incident.id == "test-audit-inc-2").first()
    assert refreshed.status == "PENDING_USER"

def test_reactive_incident_not_resolved_before_grace_window(db_session):
    # Reactive incidents should NOT be auto-resolved within 3 minutes (grace window)
    inc = Incident(
        id="test-reactive-inc-1",
        target_id="sonarr",
        status="PENDING_USER",
        origin="reactive",
        root_cause="Container crashed",
        proposed_fix="docker compose restart sonarr",
        created_at=datetime.utcnow() - timedelta(seconds=30)
    )
    db_session.add(inc)
    db_session.commit()

    docker_mock = MagicMock()
    container_mock = MagicMock()
    container_mock.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
    docker_mock.containers.get.return_value = container_mock

    with patch("docker.from_env", return_value=docker_mock):
        check_deferred_and_ignored()

    refreshed = db_session.query(Incident).filter(Incident.id == "test-reactive-inc-1").first()
    assert refreshed.status == "PENDING_USER"

def test_reactive_incident_resolved_after_grace_window_when_healthy(db_session):
    # Reactive incidents older than 3 minutes SHOULD be auto-resolved if healthy and running
    inc = Incident(
        id="test-reactive-inc-2",
        target_id="sonarr",
        status="PENDING_USER",
        origin="reactive",
        root_cause="Container crashed",
        proposed_fix="docker compose restart sonarr",
        created_at=datetime.utcnow() - timedelta(minutes=5)
    )
    db_session.add(inc)
    db_session.commit()

    docker_mock = MagicMock()
    container_mock = MagicMock()
    container_mock.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
    docker_mock.containers.get.return_value = container_mock

    with patch("docker.from_env", return_value=docker_mock):
        check_deferred_and_ignored()

    refreshed = db_session.query(Incident).filter(Incident.id == "test-reactive-inc-2").first()
    assert refreshed.status == "RESOLVED"
    assert refreshed.completed_at is not None
