import pytest
from unittest.mock import MagicMock, patch
from app.stack_watcher import StackWatcherManager
from app.database import Incident, StackAudit
from app.notifier import send_sre_digest_notification
from app.scheduler import run_daily_sre_audit


def test_audit_stack_logs_healthy_container_does_not_create_pending_incident(db_session):
    client = MagicMock()
    container = MagicMock()
    container.name = "radarr4k"
    container.attrs = {
        "Config": {"Labels": {"com.docker.compose.project": "media_content"}},
        "State": {"Running": True, "Health": {"Status": "healthy"}},
    }
    container.logs.return_value = b"2026-09-20 02:00:00 [WRN] Failed to query remote API\n"
    client.containers.list.return_value = [container]

    manager = StackWatcherManager(client=client)
    with patch("app.stack_watcher.call_sre_ai_analyst") as mock_ai:
        mock_ai.return_value = '{"containers": {"radarr4k": {"root_cause": "API timeout", "proposed_fix": "docker compose restart radarr4k", "action_required": false}}}'
        result = manager.audit_stack_logs("media_content", db=db_session)

    assert result["status"] in ["HEALTHY", "WARNING"]
    assert result.get("incident_ids") == []
    assert db_session.query(Incident).count() == 0


def test_audit_stack_logs_healthy_container_suppresses_ai_action_required(db_session):
    client = MagicMock()
    container = MagicMock()
    container.name = "sonarr"
    container.attrs = {
        "Config": {"Labels": {"com.docker.compose.project": "media_content"}},
        "State": {"Running": True, "Status": "running", "Health": {"Status": "healthy"}},
    }
    container.logs.return_value = b"2026-09-20 01:00:00 [ERROR] Failed to query remote upstream API\n"
    client.containers.list.return_value = [container]

    manager = StackWatcherManager(client=client)
    with patch("app.stack_watcher.call_sre_ai_analyst") as mock_ai:
        # AI incorrectly flags action_required as True for a running healthy container
        mock_ai.return_value = '{"containers": {"sonarr": {"root_cause": "Dropped connection", "proposed_fix": "restart", "action_required": true}}}'
        result = manager.audit_stack_logs("media_content", db=db_session)

    assert result["status"] == "WARNING"
    assert result.get("incident_ids") == []
    assert db_session.query(Incident).count() == 0


def test_audit_stack_logs_crashed_container_creates_pending_incident(db_session):
    client = MagicMock()
    container = MagicMock()
    container.name = "transmission"
    container.attrs = {
        "Config": {"Labels": {"com.docker.compose.project": "media_download"}},
        "State": {"Running": False, "Status": "exited", "ExitCode": 137},
    }
    container.logs.return_value = b"2026-09-20 02:30:00 [FATAL] Out of memory killed\n"
    client.containers.list.return_value = [container]

    manager = StackWatcherManager(client=client)
    with patch("app.stack_watcher.call_sre_ai_analyst") as mock_ai, \
         patch("app.notifier.send_incident_notification") as mock_notify:
        mock_ai.return_value = '{"containers": {"transmission": {"root_cause": "OOM Killed", "proposed_fix": "Increase memory limit", "action_required": true}}}'
        result = manager.audit_stack_logs("media_download", db=db_session)

    assert result["status"] == "ACTION_REQUIRED"
    assert len(result.get("incident_ids", [])) == 1
    incident = db_session.query(Incident).filter(Incident.target_id == "transmission").first()
    assert incident is not None
    assert incident.status == "PENDING_USER"
    mock_notify.assert_called_once_with(incident.id)


def test_audit_all_stacks_sends_single_digest_notification():
    manager = StackWatcherManager()
    mock_stacks = [{"name": "media"}, {"name": "cloud"}, {"name": "smarthome"}]

    with patch.object(manager, "discover_stacks", return_value=mock_stacks), \
         patch.object(manager, "audit_stack_logs") as mock_audit, \
         patch("app.stack_watcher.publish_sre_audit_preview", return_value="https://preview.wileyriley.com/sre-audit-daily/") as mock_preview, \
         patch("app.notifier.send_incident_notification") as mock_single_notify, \
         patch("app.notifier.send_sre_digest_notification") as mock_digest_notify:

        mock_audit.side_effect = [
            {"stack_name": "media", "status": "HEALTHY", "error_count": 0, "containers_checked": 3},
            {"stack_name": "cloud", "status": "WARNING", "error_count": 2, "containers_checked": 4},
            {"stack_name": "smarthome", "status": "ACTION_REQUIRED", "incident_ids": ["inc-1"], "error_count": 5, "containers_checked": 2},
        ]

        results = manager.audit_all_stacks()

        # Individual stack alerts must NOT fire from audit_all_stacks
        mock_single_notify.assert_not_called()
        # Preview publishing must be called
        mock_preview.assert_called_once_with(results)
        # Single consolidated digest must be fired with preview_url
        mock_digest_notify.assert_called_once_with(results, preview_url="https://preview.wileyriley.com/sre-audit-daily/")
        assert len(results) == 3


def test_send_sre_digest_notification():
    results = [
        {"stack_name": "media", "status": "HEALTHY", "error_count": 0},
        {"stack_name": "cloud", "status": "WARNING", "error_count": 3, "summary": "Cloud stack is healthy. All warnings are benign token expirations."},
        {"stack_name": "monitoring", "status": "ACTION_REQUIRED", "error_count": 1, "summary": "Grafana down"},
    ]

    with patch("requests.post") as mock_post, \
         patch("app.notifier.send_telegram_notification") as mock_tg:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        success = send_sre_digest_notification(results)
        assert success is True

        mock_tg.assert_called_once()
        assert mock_post.called

        # Check request headers and body
        call_args = mock_post.call_args
        headers = call_args[1].get("headers", {})
        data = call_args[1].get("data", b"").decode("utf-8")

        assert headers.get("Tags") == "clipboard"
        assert "view, Full Report" in headers.get("Actions", "")
        assert "view, Dashboard" in headers.get("Actions", "")
        assert "3 stacks checked" in data
        assert "1 active outages" in data
        assert "1 warnings logged" in data
        # Cloud stack was benign so it is filtered into clean summary
        assert "2 stacks clean (1 benign noise filtered)" in data
        assert len(data) <= 1200


def test_is_benign_warning():
    from app.notifier import is_benign_warning

    assert is_benign_warning("All webservices stack containers are healthy with zero actionable issues.") is True
    assert is_benign_warning("The sure stack is healthy; all logged events match known benign patterns.") is True
    assert is_benign_warning("Stack wud is healthy. Both log entries are expected benign noise.") is True
    assert is_benign_warning("Prowlarr has active connectivity failures to its integrated media apps requiring investigation.") is False
    assert is_benign_warning("ha-postgres requires attention due to index dimension issues.") is False
    assert is_benign_warning("uptime-kuma monitors pointing to dead 404 endpoints.") is False


def test_extract_concise_summary():
    from app.notifier import extract_concise_summary

    text = "Stack 'smarthome_core' is healthy. Only ha-postgres requires attention due to ContextCortex RAG schema migration issues causing repeated query failures; all other alerts are expected transient behavior."
    concise = extract_concise_summary(text, max_chars=80)
    assert len(concise) <= 85
    assert "ha-postgres requires attention" in concise


def test_generate_sre_audit_html_report():
    from app.stack_watcher import generate_sre_audit_html_report

    results = [
        {"stack_name": "media", "status": "HEALTHY", "error_count": 0, "containers_checked": 4},
        {"stack_name": "ai", "status": "WARNING", "error_count": 5, "containers_checked": 6, "summary": "AI stack is healthy. Benign notices."},
        {"stack_name": "cameras", "status": "ACTION_REQUIRED", "error_count": 12, "containers_checked": 2, "root_cause": "Frigate disk bottleneck", "proposed_fix": "docker compose restart frigate"},
    ]

    html = generate_sre_audit_html_report(results)
    assert "Daily SRE Stack Audit" in html
    assert "Frigate disk bottleneck" in html
    assert "docker compose restart frigate" in html
    assert "cameras" in html
    assert "media" in html


def test_scheduler_run_daily_sre_audit():
    with patch("app.database.check_maintenance_status", return_value=(False, "")), \
         patch("app.stack_watcher.stack_watcher_manager.audit_all_stacks", return_value=[{"stack_name": "media", "status": "HEALTHY"}]) as mock_audit:
        run_daily_sre_audit()
        mock_audit.assert_called_once()
