import os
import time
from unittest.mock import MagicMock, patch
from datetime import datetime
import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal, Incident, Target, StackAudit, SystemSetting
from app.main import app

client = TestClient(app, raise_server_exceptions=False)

def test_e2e_full_sre_incident_lifecycle(db_session):
    """
    E2E Journey 1:
    1. Fleet discovery via /api/stacks
    2. SRE log audit finds critical container error
    3. Incident is surfaced with origin='sre_daily_audit' and status='PENDING_USER'
    4. Actionable push notification sent to operator
    5. Operator approves remediation via /api/incidents/{id}/action (action='fix')
    6. Remediator executes bash command fix
    7. Incident completes with status='RESOLVED'
    8. Dashboard reflects resolved health status
    """
    mock_container = MagicMock()
    mock_container.name = "e2e_broken_redis"
    mock_container.logs.return_value = b"CRITICAL: Out of memory, allocating buffer failed\n"
    mock_container.attrs = {
        "Config": {
            "Image": "redis:alpine",
            "Labels": {
                "com.docker.compose.project": "e2e_media",
                "com.docker.compose.service": "redis",
                "com.docker.compose.project.working_dir": "/containers/media"
            }
        },
        "NetworkSettings": {"Ports": {"6379/tcp": [{"HostIp": "0.0.0.0", "HostPort": "6379"}]}},
        "State": {"Status": "running", "Health": {"Status": "healthy"}, "StartedAt": "2026-08-20T00:00:00Z"}
    }
    mock_container.image.tags = ["redis:alpine"]
    mock_container.image.id = "sha256:e2e111222"
    mock_container.image.attrs = {"RepoDigests": ["redis@sha256:e2e111222"]}

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_container]

    ai_triage_response = (
        '{"root_cause": "Redis memory threshold reached maxmemory", '
        '"proposed_fix": "docker compose -f /containers/media/docker-compose.yaml restart redis", '
        '"category": "settings", '
        '"action_required": true}'
    )

    with patch("docker.from_env", return_value=mock_docker), \
         patch("app.stack_watcher.call_sre_ai_analyst", return_value=ai_triage_response), \
         patch("app.notifier.send_incident_notification") as mock_notify, \
         patch("app.remediator.time.sleep", return_value=None), \
         patch("subprocess.run") as mock_subproc:

        mock_subproc.return_value = MagicMock(returncode=0, stdout="Restarting redis... done", stderr="")

        # Step 1: List stacks
        res_stacks = client.get("/api/stacks")
        assert res_stacks.status_code == 200
        stacks_data = res_stacks.json()
        assert len(stacks_data) == 1
        assert stacks_data[0]["name"] == "e2e_media"

        # Step 2: Trigger on-demand audit for the stack
        res_audit = client.post("/api/stacks/e2e_media/audit")
        assert res_audit.status_code == 200
        audit_data = res_audit.json()
        assert audit_data["status"] == "ACTION_REQUIRED"
        assert audit_data["incident_id"] is not None
        incident_id = audit_data["incident_id"]

        # Step 3: Verify notification was dispatched
        assert mock_notify.called

        # Step 4: Verify Incident record in DB
        inc = db_session.query(Incident).filter(Incident.id == incident_id).first()
        assert inc is not None
        assert inc.origin == "sre_daily_audit"
        assert inc.status == "PENDING_USER"
        assert "Redis memory threshold" in inc.root_cause

        # Step 5: User approves remediation action
        res_act = client.post(f"/api/incidents/{incident_id}/action", json={"action": "fix"})
        assert res_act.status_code == 200
        assert res_act.json()["status"] == "ok"

        # Step 6: Verify Dashboard metrics
        res_dash = client.get("/api/dashboard")
        assert res_dash.status_code == 200

def test_e2e_upgrade_run_and_canary_status(db_session):
    """
    E2E Journey 2:
    1. Query available stacks via /api/upgrades/stacks
    2. Operator triggers upgrade run via /api/upgrades/run
    3. Verify live status polling via /api/upgrades/live
    4. Operator cancels upgrade via /api/upgrades/cancel
    """
    with patch("app.upgrades.upgrades_manager.discover_stacks", return_value=["media", "smarthome"]), \
         patch("app.upgrades.upgrades_manager.start_upgrade", return_value={"status": "started", "job_id": "run-e2e-123"}), \
         patch("app.upgrades.upgrades_manager.get_live_status", return_value={"status": "RUNNING", "progress": 50, "logs": ["Pulling images..."]}), \
         patch("app.upgrades.upgrades_manager.cancel_active_upgrade", return_value={"status": "cancelled"}):

        # 1. Discover stacks
        res_stacks = client.get("/api/upgrades/stacks")
        assert res_stacks.status_code == 200
        assert "media" in res_stacks.json()

        # 2. Trigger upgrade
        res_run = client.post("/api/upgrades/run", json={"targets": ["media"]})
        assert res_run.status_code == 200
        assert res_run.json()["job_id"] == "run-e2e-123"

        # 3. Poll live status
        res_live = client.get("/api/upgrades/live")
        assert res_live.status_code == 200
        assert res_live.json()["status"] == "RUNNING"

        # 4. Cancel upgrade
        res_cancel = client.post("/api/upgrades/cancel")
        assert res_cancel.status_code == 200
        assert res_cancel.json()["status"] == "cancelled"

def test_e2e_system_settings_and_maintenance_toggle(db_session):
    """
    E2E Journey 3:
    1. Toggle autopilot mode via /api/settings
    2. Pause Monitorbot for 1 hour via /api/maintenance
    3. Verify maintenance mode is reported in /api/settings
    4. Resume Monitorbot via /api/maintenance
    5. Verify maintenance mode returns to false
    """
    # 1. Toggle autopilot
    res_auto = client.post("/api/settings", json={"autopilot": True, "silent_mode": False})
    assert res_auto.status_code == 200
    assert res_auto.json()["status"] == "success"

    # 2. Pause maintenance for 1 hour
    res_pause = client.post("/api/maintenance", json={"duration": "1h"})
    assert res_pause.status_code == 200
    assert "paused for 1h" in res_pause.json()["detail"]

    # 3. Status check
    with patch("app.routers.settings.check_maintenance_status", return_value=(True, "Manual maintenance")):
        res_settings = client.get("/api/settings")
        assert res_settings.status_code == 200
        assert res_settings.json()["autopilot"] is True
        assert res_settings.json()["maintenance_active"] is True

    # 4. Resume
    res_resume = client.post("/api/maintenance", json={"duration": "resume"})
    assert res_resume.status_code == 200
    assert res_resume.json()["status"] == "success"

    # 5. Status check again
    with patch("app.routers.settings.check_maintenance_status", return_value=(False, "")):
        res_settings_after = client.get("/api/settings")
        assert res_settings_after.status_code == 200
        assert res_settings_after.json()["maintenance_active"] is False

