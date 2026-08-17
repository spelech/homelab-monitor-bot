import os
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.database import (
    get_setting, set_setting, check_maintenance_status,
    Incident, Target, SessionLocal
)
from app.investigator import call_opencode_server, run_investigation_logic
from app.ai_usage import record_ai_usage, get_ai_usage_summary, calculate_cost
from app.notifier import send_incident_notification

client = TestClient(app)

def test_database_settings_helpers(db_session):
    set_setting("test_key", "test_val")
    val = get_setting("test_key")
    assert val == "test_val"

@patch("requests.post")
def test_call_opencode_server(mock_post):
    mock_post.side_effect = [
        MagicMock(status_code=200, json=lambda: {"id": "sess-123"}),
        MagicMock(status_code=200, json=lambda: {"parts": [{"type": "text", "text": "{\"root_cause\": \"OOM\"}"}]})
    ]
    res = call_opencode_server("test prompt")
    assert "root_cause" in res

def test_root_ui_legacy_fallback(monkeypatch, db_session):
    monkeypatch.setattr(os.path, "exists", lambda p: False if "index.html" in p else True)
    res = client.get("/")
    assert res.status_code == 200

def test_ai_usage_functions(db_session):
    cost = calculate_cost("gemini-2.5-flash", 1000, 500)
    assert cost > 0
    cost_zero = calculate_cost("gemini-2.5-flash", 0, 0)
    assert cost_zero == 0.0
    
    # Test record_ai_usage success
    log = record_ai_usage("inc-123", "opencode", "gemini-2.5-flash", 10, 10, 20, 0.01, 1.0, "SUCCESS")
    assert log is not None
    assert log.incident_id == "inc-123"

    # Test record_ai_usage error handling inside try/except
    mock_db = MagicMock()
    mock_db.add.side_effect = Exception("DB error")
    with patch("app.ai_usage.SessionLocal", return_value=mock_db):
        err_log = record_ai_usage("inc-123", "opencode", "model", 10, 10, 20, 0.01, 1.0, "SUCCESS")
        assert err_log is None

    # Test get_ai_usage_summary with healthy litellm
    with patch("requests.get", return_value=MagicMock(status_code=200)):
        summary = get_ai_usage_summary()
        assert summary["litellm_status"] == "healthy"
        assert summary["total_calls"] >= 1

    # Test get_ai_usage_summary error handling
    mock_db_err = MagicMock()
    mock_db_err.query.side_effect = Exception("DB query fail")
    with patch("app.ai_usage.SessionLocal", return_value=mock_db_err):
        summary_err = get_ai_usage_summary()
        assert summary_err["total_calls"] == 0
