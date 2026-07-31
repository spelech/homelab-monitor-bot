"""
tests/test_guardrails.py
~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Loop Prevention, Dependency Parsing, Command Safety Validation,
and Uptime Kuma health verification checks.
"""
import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app.database import Incident, Target
from app.dependencies import load_compose_dependencies, check_parent_incidents
from app.remediator import run_remediation

@pytest.fixture(autouse=True)
def mock_sleep():
    with patch("time.sleep") as mock:
        yield mock

# 1. Dependency Mapping parsing tests
def test_dependency_parsing(tmp_path):
    # Create temp directory layout
    project_dir = tmp_path / "finance"
    project_dir.mkdir()
    compose_file = project_dir / "docker-compose.yaml"
    
    compose_yaml = """
services:
  ledgerai:
    container_name: ledgerai
    depends_on:
      - ledgerai_db
  ledgerai_db:
    container_name: ledgerai_db
"""
    compose_file.write_text(compose_yaml)

    # Clear dependency cache
    import app.dependencies
    app.dependencies._dependency_cache = None

    deps = load_compose_dependencies(root_dir=str(tmp_path))
    assert "ledgerai" in deps
    assert deps["ledgerai"] == ["ledgerai_db"]

# 2. Dependency Check blocking remediation
def test_dependency_blocks_remediation(db_session):
    # Setup Target and Incidents
    target_child = Target(id="ledgerai", type="docker")
    target_parent = Target(id="ledgerai_db", type="docker")
    db_session.add_all([target_child, target_parent])
    db_session.commit()

    # Active incident on parent
    parent_inc = Incident(id="inc-parent", target_id="ledgerai_db", status="DETECTED")
    # Active incident on child
    child_inc = Incident(id="inc-child", target_id="ledgerai", status="PENDING_USER", proposed_fix="echo 'fixing'")
    db_session.add_all([parent_inc, child_inc])
    db_session.commit()

    # Mock dependencies map
    import app.dependencies
    app.dependencies._dependency_cache = {"ledgerai": ["ledgerai_db"]}

    run_remediation("inc-child")

    db_session.expire_all()
    child_db = db_session.query(Incident).filter_by(id="inc-child").first()
    # Remediation should have paused and status reverted to PENDING_USER
    assert child_db.status == "PENDING_USER"
    assert "Remediation paused: Unresolved parent dependencies: ledgerai_db" in child_db.execution_log

# 3. Command Safety engine checks
@pytest.mark.parametrize("unsafe_command,violation_desc", [
    ("rm -rf /config/db.sqlite", "rm -rf"),
    ("docker system prune -a --volumes", "prune"),
    ("reboot", "reboot"),
    ("docker kill container_id", "docker kill"),
    ("mv secret.key /dev/null", "/dev/null")
])
@patch("app.remediator.send_followup_notification")
def test_command_safety_blocks_unsafe_fixes(mock_notify, unsafe_command, violation_desc, db_session):
    target = Target(id="test-safety-target", type="docker")
    db_session.add(target)
    
    incident = Incident(
        id="inc-safety-test",
        target_id="test-safety-target",
        status="PENDING_USER",
        proposed_fix=unsafe_command
    )
    db_session.add(incident)
    db_session.commit()

    # Mock dependencies map to bypass dependency checks
    import app.dependencies
    app.dependencies._dependency_cache = {}

    with patch("app.notifier.send_incident_notification") as mock_alert:
        run_remediation("inc-safety-test")
        mock_alert.assert_called_once_with("inc-safety-test")

    db_session.expire_all()
    inc_db = db_session.query(Incident).filter_by(id="inc-safety-test").first()
    assert inc_db.status == "BLOCKED"
    assert "Remediation BLOCKED: Unsafe command verification failed" in inc_db.execution_log

# 4. Circuit Breaker blocks loop
@patch("app.notifier.send_incident_notification")
def test_circuit_breaker_trips(mock_notify, db_session):
    target = Target(id="loopy-service", type="docker")
    db_session.add(target)
    
    # Create two failed incidents within the last 10 minutes
    now = datetime.utcnow()
    inc1 = Incident(id="inc-loop-1", target_id="loopy-service", status="FAILED", completed_at=now - timedelta(minutes=5))
    inc2 = Incident(id="inc-loop-2", target_id="loopy-service", status="FAILED", completed_at=now - timedelta(minutes=2))
    db_session.add_all([inc1, inc2])
    db_session.commit()

    # Trigger process failure (which simulates a new failure detection)
    from app.watcher import process_failure
    mock_client = MagicMock()

    process_failure(mock_client, "loopy-service", "some-id", "Third fail event")

    db_session.expire_all()
    # There should now be a BLOCKED incident in the DB
    blocked_inc = db_session.query(Incident).filter_by(target_id="loopy-service", status="BLOCKED").first()
    assert blocked_inc is not None
    assert "Circuit breaker tripped" in blocked_inc.error_logs
    mock_notify.assert_called_once_with(blocked_inc.id)

# 5. Uptime Kuma Web Probe Healthy verification
@patch("requests.get")
@patch("docker.from_env")
def test_remediation_kuma_probe_success(mock_docker, mock_get, db_session):
    target = Target(id="kuma-service", type="docker")
    db_session.add(target)
    
    incident = Incident(
        id="inc-kuma-test",
        target_id="kuma-service",
        status="PENDING_USER",
        proposed_fix="echo 'restart'"
    )
    db_session.add(incident)
    db_session.commit()

    # Mock container labels to return kuma URL
    mock_container = MagicMock()
    mock_container.labels = {"kuma.kuma-service.http.url": "https://service.wileyriley.com"}
    mock_docker_client = MagicMock()
    mock_docker_client.containers.get.return_value = mock_container
    mock_docker.return_value = mock_docker_client

    # Mock requests to return HTTP 200 (healthy)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_get.return_value = mock_resp

    # Clear dependency cache
    import app.dependencies
    app.dependencies._dependency_cache = {}

    with patch("app.remediator.subprocess.run") as mock_run:
        # Mock successful execution
        mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
        with patch("app.remediator.send_followup_notification"):
            run_remediation("inc-kuma-test")

    db_session.expire_all()
    inc_db = db_session.query(Incident).filter_by(id="inc-kuma-test").first()
    assert inc_db.status == "RESOLVED"
    
    # Assert requests.get was called with the correct label URL
    mock_get.assert_called_once_with("https://service.wileyriley.com", timeout=5, verify=False)
