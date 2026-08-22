import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from datetime import datetime

from app.main import app
from app.database import StackAudit, Incident, Target

client = TestClient(app)


def test_get_stacks_list():
    mock_stacks = [{
        "name": "smarthome_core",
        "path": "/containers/smarthome_core",
        "status": "HEALTHY",
        "total_containers": 3,
        "running_containers": 3,
        "unhealthy_containers": 0,
        "updates_available_count": 1,
        "last_audit": {"status": "HEALTHY", "summary": "Clean", "created_at": "2026-08-22T03:00:00Z"},
        "active_incidents_count": 0
    }]
    with patch("app.stack_watcher.stack_watcher_manager.discover_stacks", return_value=mock_stacks):
        res = client.get("/api/stacks")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["name"] == "smarthome_core"
        assert data[0]["updates_available_count"] == 1


def test_get_stacks_list_enriches_db_data(db_session):
    # Insert a target, incident, and stack audit into the DB
    target = Target(id="ha_container", type="docker")
    db_session.add(target)
    
    incident = Incident(
        id="inc-sre-1",
        target_id="ha_container",
        status="PENDING_USER",
        stack_name="smarthome_core",
        origin="sre_daily_audit",
        root_cause="HA config issue",
        created_at=datetime.utcnow()
    )
    db_session.add(incident)
    
    audit = StackAudit(
        id="audit-sre-1",
        stack_name="smarthome_core",
        status="ACTION_REQUIRED",
        summary="Config issue found",
        error_count="2",
        containers_checked="3",
        created_at=datetime.utcnow()
    )
    db_session.add(audit)
    db_session.commit()

    mock_stacks = [{
        "name": "smarthome_core",
        "working_dir": "/containers/smarthome_core",
        "config_files": "/containers/smarthome_core/docker-compose.yaml",
        "status": "degraded",
        "total_containers": 3,
        "running_containers": 2,
        "healthy_containers": 2,
        "unhealthy_containers": 1,
        "containers": [{"name": "ha_container", "image": "homeassistant:latest"}]
    }]

    with patch("app.stack_watcher.stack_watcher_manager.discover_stacks", return_value=mock_stacks):
        res = client.get("/api/stacks")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["name"] == "smarthome_core"
        assert data[0]["active_incidents_count"] == 1
        assert data[0]["last_audit"] is not None
        assert data[0]["last_audit"]["status"] == "ACTION_REQUIRED"
        assert data[0]["last_audit"]["summary"] == "Config issue found"


def test_get_stack_details_found(db_session):
    audit = StackAudit(
        id="audit-detail-1",
        stack_name="media",
        status="HEALTHY",
        summary="Clean run",
        error_count="0",
        containers_checked="4",
        created_at=datetime.utcnow()
    )
    db_session.add(audit)
    db_session.commit()

    mock_stack = {
        "name": "media",
        "working_dir": "/containers/media",
        "config_files": "/containers/media/docker-compose.yaml",
        "status": "healthy",
        "total_containers": 2,
        "running_containers": 2,
        "healthy_containers": 2,
        "unhealthy_containers": 0,
        "containers": [
            {"name": "plex", "image": "plex:latest", "status": "running"},
            {"name": "radarr", "image": "radarr:latest", "status": "running"}
        ]
    }

    with patch("app.stack_watcher.stack_watcher_manager.get_stack_details", return_value=mock_stack):
        res = client.get("/api/stacks/media")
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "media"
        assert data["total_containers"] == 2
        assert len(data["containers"]) == 2
        assert data["last_audit"]["status"] == "HEALTHY"
        assert len(data["audit_history"]) >= 1


def test_get_stack_details_not_found():
    with patch("app.stack_watcher.stack_watcher_manager.get_stack_details", return_value=None):
        res = client.get("/api/stacks/non_existent_stack")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()


def test_audit_stack_endpoint():
    mock_res = {"status": "HEALTHY", "stack_name": "smarthome_core", "error_count": 0, "summary": "All good"}
    with patch("app.stack_watcher.stack_watcher_manager.audit_stack_logs", return_value=mock_res):
        res = client.post("/api/stacks/smarthome_core/audit")
        assert res.status_code == 200
        assert res.json()["status"] == "HEALTHY"
        assert res.json()["stack_name"] == "smarthome_core"


def test_check_stack_updates_endpoint():
    mock_res = {"stack_name": "smarthome_core", "updates_count": 1, "total_checked": 2, "containers": []}
    with patch("app.stack_watcher.stack_watcher_manager.check_stack_updates", return_value=mock_res):
        res = client.post("/api/stacks/smarthome_core/check-updates")
        assert res.status_code == 200
        assert res.json()["updates_count"] == 1
        assert res.json()["stack_name"] == "smarthome_core"


def test_audit_all_stacks_endpoint():
    mock_results = [
        {"stack_name": "media", "status": "HEALTHY", "error_count": 0},
        {"stack_name": "webservices", "status": "HEALTHY", "error_count": 0}
    ]
    with patch("app.stack_watcher.stack_watcher_manager.audit_all_stacks", return_value=mock_results):
        res = client.post("/api/stacks/audit-all")
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 2
        assert data[0]["stack_name"] == "media"
        assert data[1]["stack_name"] == "webservices"
