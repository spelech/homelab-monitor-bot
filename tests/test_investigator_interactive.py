import pytest
from unittest.mock import patch, MagicMock
import requests
from app.investigator import (
    call_ai_investigate_session,
    AI_DISPATCH_URL,
    AI_MODEL,
)

def test_call_ai_investigate_session_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "session_id": "conv-test-123",
        "executor": "opencode",
        "success": True,
        "root_cause": "Port conflict on 8080",
        "proposed_fix": "docker compose restart app",
        "category": "network",
        "raw_output": '{"root_cause": "Port conflict on 8080", "proposed_fix": "docker compose restart app", "category": "network"}',
        "turns_used": 2,
        "transcript": [
            {"role": "user", "turn": 1, "content": "investigate"},
            {"role": "assistant", "turn": 1, "content": "checking"},
            {"role": "assistant", "turn": 2, "content": "fixed"}
        ]
    }

    with patch("app.investigator.requests.post", return_value=mock_resp) as mock_post:
        data, duration = call_ai_investigate_session(
            target="my-app",
            error_logs="Address already in use :8080",
            notes="historical note",
            executor="opencode",
            max_turns=3,
            timeout=45
        )

        assert data["session_id"] == "conv-test-123"
        assert data["root_cause"] == "Port conflict on 8080"
        assert data["proposed_fix"] == "docker compose restart app"
        assert data["category"] == "network"
        assert len(data["transcript"]) == 3
        assert isinstance(duration, float)
        assert duration >= 0.0

        mock_post.assert_called_once_with(
            f"{AI_DISPATCH_URL}/investigate",
            json={
                "target": "my-app",
                "exit_code": 1,
                "error_logs": "Address already in use :8080",
                "notes": "historical note",
                "executor": "opencode",
                "max_turns": 3,
                "timeout": 45
            },
            timeout=45
        )


def test_investigation_logic_prefers_interactive_sre(db_session):
    from app.database import Incident, Target
    from app.investigator import run_investigation_logic

    target = Target(id="interactive-target", type="docker")
    db_session.add(target)
    inc = Incident(
        id="interactive-uuid-1",
        target_id="interactive-target",
        status="DETECTED",
        error_logs="OOMKilled"
    )
    db_session.add(inc)
    db_session.commit()

    investigate_result = {
        "session_id": "sess-oom-99",
        "executor": "opencode",
        "success": True,
        "root_cause": "Container ran out of memory",
        "proposed_fix": "docker compose up -d interactive-target",
        "category": "resources",
        "raw_output": '{"root_cause": "Container ran out of memory", "proposed_fix": "docker compose up -d interactive-target", "category": "resources"}',
        "turns_used": 1,
        "transcript": [{"role": "assistant", "turn": 1, "content": "inspected memory limit"}]
    }

    with patch("app.investigator.call_ai_investigate_session", return_value=(investigate_result, 1.1)) as mock_inv, \
         patch("app.investigator.call_ai_dispatch_server") as mock_fallback_dispatch, \
         patch("subprocess.run") as mock_subproc, \
         patch("app.notifier.send_incident_notification") as mock_notify:

        run_investigation_logic(db_session, inc)

        db_session.refresh(inc)
        assert inc.status == "PENDING_USER"
        assert inc.root_cause == "Container ran out of memory"
        assert inc.proposed_fix == "docker compose up -d interactive-target"
        assert inc.category == "resources"
        mock_inv.assert_called_once()
        mock_fallback_dispatch.assert_not_called()
        mock_subproc.assert_not_called()
        mock_notify.assert_called_once()
