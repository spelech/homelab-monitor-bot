from unittest.mock import MagicMock, patch
import json
from datetime import datetime
from app.database import Incident, StackAudit, Target
from app.stack_watcher import StackWatcherManager
from app.prompts import build_sre_audit_prompt


def test_audit_stack_logs_creates_per_container_incidents(db_session):
    manager = StackWatcherManager()

    # Mock containers
    c1 = MagicMock()
    c1.name = "radarr4k"
    c1.attrs = {"Name": "/radarr4k", "Config": {"Labels": {"com.docker.compose.project": "media"}}}
    c1.logs.return_value = b"[Error] JSON deserialization failed in Radarr"

    c2 = MagicMock()
    c2.name = "sonarrhd"
    c2.attrs = {"Name": "/sonarrhd", "Config": {"Labels": {"com.docker.compose.project": "media"}}}
    c2.logs.return_value = b"[Error] SeriesScannedEvent failed"

    manager.client = MagicMock()
    manager.client.containers.list.return_value = [c1, c2]

    ai_response = json.dumps({
        "containers": {
            "radarr4k": {
                "root_cause": "Malformed metadata API response",
                "proposed_fix": "Clear metadata cache",
                "category": "api_error",
                "action_required": True
            },
            "sonarrhd": {
                "root_cause": "Corrupted event queue",
                "proposed_fix": "Restart Sonarr container",
                "category": "app_crash",
                "action_required": True
            }
        },
        "overall_summary": "Two independent application errors in media stack."
    })

    with patch("app.stack_watcher.call_sre_ai_analyst", return_value=ai_response):
        with patch("app.notifier.send_incident_notification"):
            res = manager.audit_stack_logs("media", db=db_session)

    assert res["status"] == "ACTION_REQUIRED"
    assert len(res["incident_ids"]) == 2

    inc_radarr = db_session.query(Incident).filter(Incident.target_id == "radarr4k").first()
    assert inc_radarr is not None
    assert inc_radarr.root_cause == "Malformed metadata API response"
    assert "JSON deserialization failed" in inc_radarr.error_logs

    inc_sonarr = db_session.query(Incident).filter(Incident.target_id == "sonarrhd").first()
    assert inc_sonarr is not None
    assert inc_sonarr.root_cause == "Corrupted event queue"
    assert "SeriesScannedEvent failed" in inc_sonarr.error_logs


def test_audit_stack_logs_backward_compatibility_flat_json(db_session):
    manager = StackWatcherManager()

    c1 = MagicMock()
    c1.name = "radarr4k"
    c1.attrs = {"Name": "/radarr4k", "Config": {"Labels": {"com.docker.compose.project": "media"}}}
    c1.logs.return_value = b"[Error] Single legacy error"

    manager.client = MagicMock()
    manager.client.containers.list.return_value = [c1]

    ai_response = json.dumps({
        "root_cause": "Legacy single issue format",
        "proposed_fix": "Restart stack",
        "category": "settings",
        "action_required": True
    })

    with patch("app.stack_watcher.call_sre_ai_analyst", return_value=ai_response):
        with patch("app.notifier.send_incident_notification"):
            res = manager.audit_stack_logs("media", db=db_session)

    assert res["status"] == "ACTION_REQUIRED"
    assert len(res["incident_ids"]) == 1
    assert res["incident_id"] == res["incident_ids"][0]

    inc = db_session.query(Incident).filter(Incident.target_id == "radarr4k").first()
    assert inc is not None
    assert inc.root_cause == "Legacy single issue format"


def test_audit_stack_logs_partial_container_action_required(db_session):
    manager = StackWatcherManager()

    c1 = MagicMock()
    c1.name = "radarr4k"
    c1.attrs = {"Name": "/radarr4k", "Config": {"Labels": {"com.docker.compose.project": "media"}}}
    c1.logs.return_value = b"[Error] Critical API error"

    c2 = MagicMock()
    c2.name = "sonarrhd"
    c2.attrs = {"Name": "/sonarrhd", "Config": {"Labels": {"com.docker.compose.project": "media"}}}
    c2.logs.return_value = b"[Warn] Transient network timeout"

    manager.client = MagicMock()
    manager.client.containers.list.return_value = [c1, c2]

    ai_response = json.dumps({
        "containers": {
            "radarr4k": {
                "root_cause": "Critical API error",
                "proposed_fix": "Fix API key",
                "category": "api_error",
                "action_required": True
            },
            "sonarrhd": {
                "root_cause": "Transient network timeout",
                "proposed_fix": "none",
                "category": "transient_warning",
                "action_required": False
            }
        },
        "overall_summary": "Radarr has issue, Sonarr is benign."
    })

    with patch("app.stack_watcher.call_sre_ai_analyst", return_value=ai_response):
        with patch("app.notifier.send_incident_notification"):
            res = manager.audit_stack_logs("media", db=db_session)

    assert res["status"] == "ACTION_REQUIRED"
    assert len(res["incident_ids"]) == 1
    assert res["incident_ids"][0] == res["incident_id"]

    inc_radarr = db_session.query(Incident).filter(Incident.target_id == "radarr4k").first()
    assert inc_radarr is not None
    assert inc_radarr.root_cause == "Critical API error"

    inc_sonarr = db_session.query(Incident).filter(Incident.target_id == "sonarrhd").first()
    assert inc_sonarr is None


def test_audit_stack_logs_all_benign_per_container(db_session):
    manager = StackWatcherManager()

    c1 = MagicMock()
    c1.name = "radarr4k"
    c1.attrs = {"Name": "/radarr4k", "Config": {"Labels": {"com.docker.compose.project": "media"}}}
    c1.logs.return_value = b"[Warn] Warning 1"

    manager.client = MagicMock()
    manager.client.containers.list.return_value = [c1]

    ai_response = json.dumps({
        "containers": {
            "radarr4k": {
                "root_cause": "Benign warning",
                "proposed_fix": "none",
                "category": "transient_warning",
                "action_required": False
            }
        },
        "overall_summary": "All benign"
    })

    with patch("app.stack_watcher.call_sre_ai_analyst", return_value=ai_response):
        with patch("app.notifier.send_incident_notification"):
            res = manager.audit_stack_logs("media", db=db_session)

    assert res["status"] == "WARNING"
    assert res.get("incident_id") is None
    assert len(res.get("incident_ids", [])) == 0
    assert db_session.query(Incident).count() == 0


def test_build_sre_audit_prompt_format():
    prompt = build_sre_audit_prompt("media", "=== Container: radarr4k ===\n[Error] test")
    assert "Evaluate each container independently" in prompt
    assert '"containers": {' in prompt
    assert '"overall_summary"' in prompt
