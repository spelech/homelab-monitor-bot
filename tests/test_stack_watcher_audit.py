from unittest.mock import MagicMock, patch
import pytest
from app.database import SessionLocal, Incident, StackAudit, Target
from app.stack_watcher import StackWatcherManager, call_sre_ai_analyst
from app.scheduler import run_daily_sre_audit


def test_audit_stack_logs_clean_when_no_errors(db_session):
    mock_container = MagicMock()
    mock_container.name = "homeassistant"
    mock_container.logs.return_value = b"INFO: Home Assistant started cleanly\nINFO: Syncing state\n"
    mock_container.attrs = {"Config": {"Labels": {"com.docker.compose.project": "smarthome_core"}}}

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_container]

    with patch("docker.from_env", return_value=mock_docker):
        manager = StackWatcherManager()
        res = manager.audit_stack_logs("smarthome_core")
        assert res["status"] == "HEALTHY"
        assert res["error_count"] == 0
        
        audit = db_session.query(StackAudit).filter(StackAudit.stack_name == "smarthome_core").first()
        assert audit is not None
        assert audit.status == "HEALTHY"


def test_audit_stack_logs_creates_incident_on_actionable_error(db_session):
    mock_container = MagicMock()
    mock_container.name = "postgres"
    mock_container.logs.return_value = b"FATAL: database disk is full: could not write block\nPANIC: lock failure\n"
    mock_container.attrs = {"Config": {"Labels": {"com.docker.compose.project": "smarthome_support"}}}

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_container]

    mock_ai_output = """{
        "root_cause": "Postgres storage disk is full",
        "proposed_fix": "docker system prune -af && df -h",
        "category": "database",
        "action_required": true
    }"""

    with patch("docker.from_env", return_value=mock_docker), \
         patch("app.stack_watcher.call_sre_ai_analyst", return_value=mock_ai_output), \
         patch("app.notifier.send_incident_notification") as mock_notify:
        
        manager = StackWatcherManager()
        res = manager.audit_stack_logs("smarthome_support")
        assert res["status"] == "ACTION_REQUIRED"
        assert res["incident_id"] is not None

        incident = db_session.query(Incident).filter(Incident.id == res["incident_id"]).first()
        assert incident is not None
        assert incident.stack_name == "smarthome_support"
        assert incident.origin == "sre_daily_audit"
        assert incident.status == "PENDING_USER"
        mock_notify.assert_called_once_with(incident.id)


def test_audit_stack_logs_benign_warning_no_action_required(db_session):
    mock_container = MagicMock()
    mock_container.name = "zigbee2mqtt"
    mock_container.logs.return_value = b"WARN: Zigbee device temporarily offline, retrying\n"
    mock_container.attrs = {"Config": {"Labels": {"com.docker.compose.project": "smarthome_core"}}}

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_container]

    mock_ai_output = """{
        "root_cause": "Transient device reconnect warning",
        "proposed_fix": "none",
        "category": "unknown",
        "action_required": false
    }"""

    with patch("docker.from_env", return_value=mock_docker), \
         patch("app.stack_watcher.call_sre_ai_analyst", return_value=mock_ai_output), \
         patch("app.notifier.send_incident_notification") as mock_notify:
        
        manager = StackWatcherManager()
        res = manager.audit_stack_logs("smarthome_core")
        assert res["status"] == "WARNING"
        assert res.get("incident_id") is None
        assert res["error_count"] > 0

        # No incident should be created when action_required is False
        assert db_session.query(Incident).count() == 0
        mock_notify.assert_not_called()

        audit = db_session.query(StackAudit).filter(StackAudit.stack_name == "smarthome_core").first()
        assert audit is not None
        assert audit.status == "WARNING"


def test_audit_stack_logs_no_matching_containers(db_session):
    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = []

    with patch("docker.from_env", return_value=mock_docker):
        manager = StackWatcherManager()
        res = manager.audit_stack_logs("nonexistent_stack")
        assert res["status"] == "HEALTHY"
        assert res["error_count"] == 0
        assert res["containers_checked"] == 0


def test_audit_all_stacks(db_session):
    manager = StackWatcherManager()
    mock_stacks = [{"name": "media"}, {"name": "cloud"}]

    with patch.object(manager, "discover_stacks", return_value=mock_stacks), \
         patch.object(manager, "audit_stack_logs") as mock_audit:
        
        mock_audit.side_effect = [
            {"stack_name": "media", "status": "HEALTHY", "error_count": 0},
            {"stack_name": "cloud", "status": "ACTION_REQUIRED", "incident_id": "inc-123", "error_count": 5},
        ]

        results = manager.audit_all_stacks()
        assert len(results) == 2
        assert results[0]["stack_name"] == "media"
        assert results[1]["status"] == "ACTION_REQUIRED"
        assert mock_audit.call_count == 2


def test_audit_all_stacks_handles_exception(db_session):
    manager = StackWatcherManager()
    mock_stacks = [{"name": "broken_stack"}]

    with patch.object(manager, "discover_stacks", return_value=mock_stacks), \
         patch.object(manager, "audit_stack_logs", side_effect=Exception("Docker socket error")):
        
        results = manager.audit_all_stacks()
        assert len(results) == 1
        assert results[0]["stack_name"] == "broken_stack"
        assert results[0]["status"] == "FAILED"


def test_run_daily_sre_audit_scheduler_job(db_session):
    with patch("app.database.check_maintenance_status", return_value=(False, "")), \
         patch("app.stack_watcher.stack_watcher_manager.audit_all_stacks", return_value=[{"stack_name": "media", "status": "HEALTHY"}]) as mock_audit_all:
        
        run_daily_sre_audit()
        mock_audit_all.assert_called_once()


def test_run_daily_sre_audit_skipped_during_maintenance(db_session):
    with patch("app.database.check_maintenance_status", return_value=(True, "Manual maintenance")), \
         patch("app.stack_watcher.stack_watcher_manager.audit_all_stacks") as mock_audit_all:
        
        run_daily_sre_audit()
        mock_audit_all.assert_not_called()


def test_call_sre_ai_analyst_opencode_server():
    with patch.dict("os.environ", {"AI_EXECUTOR": "opencode"}), \
         patch("app.investigator.call_opencode_server", return_value='{"root_cause": "test"}') as mock_server:
        
        out = call_sre_ai_analyst("test prompt")
        assert 'root_cause' in out
        mock_server.assert_called_once_with("test prompt")


def test_call_sre_ai_analyst_opencode_cli_fallback():
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = '{"root_cause": "fallback"}'

    with patch.dict("os.environ", {"AI_EXECUTOR": "opencode"}), \
         patch("app.investigator.call_opencode_server", side_effect=Exception("Connection refused")), \
         patch("subprocess.run", return_value=mock_res) as mock_run:
        
        out = call_sre_ai_analyst("test prompt")
        assert 'fallback' in out
        mock_run.assert_called_once()


def test_call_sre_ai_analyst_agy():
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = '{"root_cause": "agy result"}'

    with patch.dict("os.environ", {"AI_EXECUTOR": "agy"}), \
         patch("subprocess.run", return_value=mock_res) as mock_run:
        
        out = call_sre_ai_analyst("test prompt")
        assert 'agy result' in out
        mock_run.assert_called_once()
