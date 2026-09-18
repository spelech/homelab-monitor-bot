import pytest
from unittest.mock import patch, MagicMock
import requests
from app.investigator import (
    call_ai_dispatch_server,
    AI_DISPATCH_URL,
    AI_MODEL,
    AI_DISPATCH_TIMEOUT,
)

def test_call_ai_dispatch_server_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "chatcmpl-123",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"root_cause": "test", "proposed_fix": "restart container"}'
                },
                "finish_reason": "stop"
            }
        ]
    }

    with patch("app.investigator.requests.post", return_value=mock_resp) as mock_post:
        content, duration = call_ai_dispatch_server(
            prompt="Investigate failure",
            model_id="opencode",
            timeout=60
        )

        assert content == '{"root_cause": "test", "proposed_fix": "restart container"}'
        assert isinstance(duration, float)
        assert duration >= 0.0

        mock_post.assert_called_once_with(
            f"{AI_DISPATCH_URL}/chat/completions",
            json={
                "model": "opencode",
                "messages": [{"role": "user", "content": "Investigate failure"}],
                "temperature": 0.2
            },
            timeout=60
        )

def test_call_ai_dispatch_server_empty_choices():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": []}

    with patch("app.investigator.requests.post", return_value=mock_resp):
        with pytest.raises(ValueError, match="No choices returned from AI dispatch gateway"):
            call_ai_dispatch_server(prompt="Test empty")

def test_call_ai_dispatch_server_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Internal Server Error")

    with patch("app.investigator.requests.post", return_value=mock_resp):
        with pytest.raises(requests.exceptions.HTTPError):
            call_ai_dispatch_server(prompt="Investigate failure")

def test_investigation_logic_uses_ai_dispatch_http(db_session):
    from app.database import Incident, Target
    from app.investigator import run_investigation_logic

    target = Target(id="test-http-target", type="docker")
    db_session.add(target)
    inc = Incident(
        id="test-http-uuid",
        target_id="test-http-target",
        status="DETECTED",
        error_logs="Database connection refused"
    )
    db_session.add(inc)
    db_session.commit()

    http_output = '{"root_cause": "Database connection refused", "proposed_fix": "docker restart test-http-target", "category": "database"}'

    with patch("app.investigator.call_ai_dispatch_server", return_value=(http_output, 1.25)) as mock_dispatch, \
         patch("subprocess.run") as mock_subproc, \
         patch("app.notifier.send_incident_notification") as mock_notify:

        run_investigation_logic(db_session, inc)

        db_session.refresh(inc)
        assert inc.status == "PENDING_USER"
        assert inc.root_cause == "Database connection refused"
        assert inc.proposed_fix == "docker restart test-http-target"
        assert inc.category == "database"
        mock_dispatch.assert_called_once()
        mock_subproc.assert_not_called()
        mock_notify.assert_called_once()

def test_investigation_fallback_to_cli_when_http_fails(db_session):
    from app.database import Incident, Target
    from app.investigator import run_investigation_logic

    target = Target(id="test-fb-target", type="docker")
    db_session.add(target)
    inc = Incident(
        id="test-fb-uuid",
        target_id="test-fb-target",
        status="DETECTED",
        error_logs="Fatal error in container"
    )
    db_session.add(inc)
    db_session.commit()

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = '{"root_cause": "CLI fallback cause", "proposed_fix": "docker restart test-fb-target", "category": "crash"}'
    mock_res.stderr = ""

    with patch("app.investigator.call_ai_dispatch_server", side_effect=Exception("HTTP connection refused")) as mock_dispatch, \
         patch("subprocess.run", return_value=mock_res) as mock_subproc, \
         patch("app.notifier.send_incident_notification") as mock_notify:

        run_investigation_logic(db_session, inc)

        db_session.refresh(inc)
        assert inc.status == "PENDING_USER"
        assert inc.root_cause == "CLI fallback cause"
        assert inc.proposed_fix == "docker restart test-fb-target"
        assert inc.category == "crash"
        mock_dispatch.assert_called_once()
        mock_subproc.assert_called_once()
        mock_notify.assert_called_once()

def test_investigation_both_http_and_cli_fail(db_session):
    from app.database import Incident, Target
    from app.investigator import run_investigation_logic

    target = Target(id="test-fail-target", type="docker")
    db_session.add(target)
    inc = Incident(
        id="test-fail-uuid",
        target_id="test-fail-target",
        status="DETECTED",
        error_logs="Crash loop"
    )
    db_session.add(inc)
    db_session.commit()

    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stderr = "CLI execution crashed"
    mock_res.stdout = ""

    with patch("app.investigator.call_ai_dispatch_server", side_effect=Exception("HTTP unreachable")) as mock_dispatch, \
         patch("subprocess.run", return_value=mock_res) as mock_subproc, \
         patch("app.notifier.send_incident_notification") as mock_notify:

        run_investigation_logic(db_session, inc)

        db_session.refresh(inc)
        assert inc.status == "FAILED"
        assert "CLI execution crashed" in inc.execution_log
        mock_dispatch.assert_called_once()
        mock_subproc.assert_called_once()
        mock_notify.assert_not_called()


