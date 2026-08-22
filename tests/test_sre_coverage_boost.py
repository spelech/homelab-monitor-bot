import os
import time
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
import docker.errors

from app.database import SessionLocal, Incident, Target, StackAudit, SystemSetting
from app.stack_watcher import (
    StackWatcherManager,
    parse_image_reference,
    call_sre_ai_analyst
)
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

def test_parse_image_reference_edge_cases():
    # 1. Custom registry with port
    res1 = parse_image_reference("localhost:5000/my-app:v1.0")
    assert res1["registry"] == "localhost:5000"
    assert res1["repository"] == "my-app"
    assert res1["tag"] == "v1.0"

    # 2. Tag with sha256 or empty
    res2 = parse_image_reference("redis")
    assert res2["registry"] == "registry-1.docker.io"
    assert res2["repository"] == "library/redis"
    assert res2["tag"] == "latest"

    # 3. Empty input
    res3 = parse_image_reference("")
    assert res3["repository"] == ""

def test_stack_watcher_client_connection_error():
    with patch("docker.from_env", side_effect=docker.errors.DockerException("Daemon down")):
        manager = StackWatcherManager()
        stacks = manager.discover_stacks()
        assert stacks == []

def test_stack_watcher_parse_container_edge_cases():
    manager = StackWatcherManager()
    mock_container = MagicMock()
    mock_container.name = "broken_props"
    mock_container.attrs = {
        "Config": {"Image": "custom:local", "Labels": None},
        "NetworkSettings": {"Ports": {"80/tcp": "invalid_format"}},
        "State": {"Status": "running", "Health": None, "StartedAt": "2026-08-01T00:00:00Z"}
    }
    mock_container.image.tags = []
    mock_container.image.id = "sha256:333333333333"
    mock_container.image.attrs = {}

    parsed = manager._parse_container(mock_container)
    assert parsed["name"] == "broken_props"
    assert parsed["project"] == "standalone"
    assert parsed["ports"] == ["80/tcp"]
    assert parsed["health"] == "none"

def test_fetch_remote_digest_edge_cases():
    manager = StackWatcherManager()

    # 1. Head returns 200 with docker-content-digest
    with patch("requests.head") as mock_head:
        mock_head.return_value = MagicMock(status_code=200, headers={"docker-content-digest": "sha256:mock_digest_head"})
        digest = manager._fetch_remote_digest("registry-1.docker.io", "library/ubuntu", "latest")
        assert digest == "sha256:mock_digest_head"

def test_fetch_remote_digest_network_error():
    manager = StackWatcherManager()
    with patch("requests.head", side_effect=Exception("Network down")):
        digest_err = manager._fetch_remote_digest("registry-1.docker.io", "library/ubuntu", "latest")
        assert digest_err is None

def test_check_stack_updates_not_found_or_empty():
    manager = StackWatcherManager()
    with patch.object(manager, "discover_stacks", return_value=[]):
        res = manager.check_stack_updates("nonexistent_stack")
        assert res["updates_count"] == 0
        assert res["total_checked"] == 0

def test_check_stack_updates_handles_container_error():
    manager = StackWatcherManager()
    mock_stack = {
        "name": "test_err_stack",
        "containers": [{"name": "c1", "image": "img1:latest", "repo_digests": [], "image_id": "sha256:111"}]
    }
    with patch.object(manager, "discover_stacks", return_value=[mock_stack]), \
         patch.object(manager, "check_container_update", side_effect=Exception("Registry crash")):
        res = manager.check_stack_updates("test_err_stack")
        assert res["stack_name"] == "test_err_stack"
        assert len(res["containers"]) == 1
        assert res["containers"][0]["status"] == "UNKNOWN"

def test_call_sre_ai_analyst_opencode_api_fallback_to_cli():
    with patch("requests.post", side_effect=Exception("API refused")), \
         patch("subprocess.run") as mock_subproc, \
         patch("app.ai_usage.record_ai_usage"):
        mock_subproc.return_value = MagicMock(returncode=0, stdout='{"root_cause": "Test CLI fix"}', stderr="")

        res = call_sre_ai_analyst("Test prompt")
        assert '{"root_cause": "Test CLI fix"}' in res

def test_call_sre_ai_analyst_cli_failure_raises():
    with patch("requests.post", side_effect=Exception("API down")), \
         patch("subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(returncode=1, stderr="CLI failure", stdout="")
        with pytest.raises(RuntimeError):
            call_sre_ai_analyst("Test prompt")

def test_audit_stack_logs_stack_not_found(db_session):
    manager = StackWatcherManager()
    with patch.object(manager, "discover_stacks", return_value=[]):
        res = manager.audit_stack_logs("ghost_stack", db=db_session)
        assert res["status"] == "HEALTHY"
        assert "No containers found" in res["summary"]

def test_audit_stack_logs_container_log_error(db_session):
    manager = StackWatcherManager()
    mock_container = MagicMock()
    mock_container.name = "log_fail_container"
    mock_container.logs.side_effect = Exception("Logs corrupted")
    mock_container.attrs = {"Config": {"Labels": {"com.docker.compose.project": "test_log_err"}}}

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_container]

    with patch("docker.from_env", return_value=mock_docker):
        res = manager.audit_stack_logs("test_log_err", db=db_session)
        assert res["status"] == "HEALTHY"
        assert res["error_count"] == 0

def test_audit_stack_logs_ai_failure_fallback(db_session):
    manager = StackWatcherManager()
    mock_container = MagicMock()
    mock_container.name = "broken_app"
    mock_container.logs.return_value = b"FATAL: catastrophic database crash\n"
    mock_container.attrs = {"Config": {"Labels": {"com.docker.compose.project": "broken_stack"}}}

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_container]

    with patch("docker.from_env", return_value=mock_docker), \
         patch("app.stack_watcher.call_sre_ai_analyst", side_effect=RuntimeError("AI offline")), \
         patch("app.notifier.send_incident_notification"):
        res = manager.audit_stack_logs("broken_stack", db=db_session)
        assert res["status"] == "ACTION_REQUIRED"
        assert res["incident_id"] is not None

def test_audit_all_stacks_handles_individual_stack_exception():
    manager = StackWatcherManager()
    with patch.object(manager, "discover_stacks", return_value=[{"name": "s1"}, {"name": "s2"}]), \
         patch.object(manager, "audit_stack_logs", side_effect=[Exception("Stack 1 crash"), {"status": "HEALTHY", "stack_name": "s2"}]):
        results = manager.audit_all_stacks()
        assert len(results) == 2
        assert results[0]["status"] == "FAILED"
        assert results[1]["status"] == "HEALTHY"

def test_routers_stacks_endpoints_error_branches():
    # 1. GET /api/stacks exception handling
    with patch("app.stack_watcher.stack_watcher_manager.discover_stacks", side_effect=Exception("Docker down")):
        res = client.get("/api/stacks")
        assert res.status_code == 500

    # 2. GET /api/stacks/{stack_name} not found
    with patch("app.stack_watcher.stack_watcher_manager.get_stack_details", return_value=None):
        res = client.get("/api/stacks/nonexistent")
        assert res.status_code == 404

    # 3. POST /api/stacks/{stack_name}/audit exception handling
    with patch("app.stack_watcher.stack_watcher_manager.audit_stack_logs", side_effect=Exception("Audit failure")):
        res = client.post("/api/stacks/smarthome_core/audit")
        assert res.status_code == 500

    # 4. POST /api/stacks/{stack_name}/check-updates exception handling
    with patch("app.stack_watcher.stack_watcher_manager.check_stack_updates", side_effect=Exception("Update check fail")):
        res = client.post("/api/stacks/smarthome_core/check-updates")
        assert res.status_code == 500

    # 5. POST /api/stacks/audit-all exception handling
    with patch("app.stack_watcher.stack_watcher_manager.audit_all_stacks", side_effect=Exception("Audit all fail")):
        res = client.post("/api/stacks/audit-all")
        assert res.status_code == 500

def test_notifier_sre_audit_incident_formatting(db_session):
    from app.notifier import send_incident_notification
    incident = Incident(
        id="sre-test-notify-1",
        target_id="smarthome_core",
        stack_name="smarthome_core",
        origin="sre_daily_audit",
        status="PENDING_USER",
        root_cause="Database connection pool exhausted",
        proposed_fix="docker restart postgres",
        category="database",
        error_logs="FATAL: pool exhausted"
    )
    db_session.add(Target(id="smarthome_core", type="docker"))
    db_session.add(incident)
    db_session.commit()

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        send_incident_notification(incident.id)
        assert mock_post.called

def test_scheduler_systemd_circuit_breaker_tripping(db_session):
    from app.scheduler import check_systemd_services
    from datetime import datetime, timedelta

    db_session.add(Target(id="failing.service", type="systemd"))
    # Add two recent failures within 60 mins
    db_session.add(Incident(
        id="prev-fail-1",
        target_id="failing.service",
        status="FAILED",
        completed_at=datetime.utcnow() - timedelta(minutes=10),
        created_at=datetime.utcnow() - timedelta(minutes=15)
    ))
    db_session.add(Incident(
        id="prev-fail-2",
        target_id="failing.service",
        status="FAILED",
        completed_at=datetime.utcnow() - timedelta(minutes=5),
        created_at=datetime.utcnow() - timedelta(minutes=8)
    ))
    db_session.commit()

    with patch("os.getenv", return_value="failing.service"), \
         patch("subprocess.run") as mock_subproc, \
         patch("app.database.check_maintenance_status", return_value=(False, "")), \
         patch("app.notifier.send_incident_notification"):
        mock_subproc.return_value = MagicMock(returncode=1)

        check_systemd_services()
        blocked_inc = db_session.query(Incident).filter(
            Incident.target_id == "failing.service",
            Incident.status == "BLOCKED"
        ).first()
        assert blocked_inc is not None
        assert "Circuit breaker tripped" in blocked_inc.error_logs
