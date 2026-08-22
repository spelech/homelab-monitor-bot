import os
import time
from unittest.mock import patch, mock_open
from app.database import (
    check_maintenance_status,
    init_db,
    SessionLocal,
    SystemSetting,
    StackAudit,
    Incident,
    Target,
    get_latest_agent_activity_timestamp,
    set_internal_ai_context,
    clear_internal_ai_context,
    is_internal_ai_context,
    internal_ai_context,
)

def test_idle_agent_session_not_in_maintenance(db_session, tmp_path):
    # Simulate an agy process running in /proc with an old transcript (> 5 mins old)
    old_mtime = time.time() - 600
    mock_transcript = tmp_path / "transcript.jsonl"
    mock_transcript.write_text('{"type": "USER_INPUT"}')
    os.utime(str(mock_transcript), (old_mtime, old_mtime))

    with patch("os.listdir", return_value=["12345"]), \
         patch("builtins.open", mock_open(read_data="agy --print")), \
         patch("app.database.get_latest_agent_activity_timestamp", return_value=old_mtime):
        is_maint, reason = check_maintenance_status(db_session)
        assert is_maint is False
        assert reason == ""

def test_active_agent_session_triggers_maintenance(db_session):
    recent_mtime = time.time() - 30  # 30 seconds ago
    with patch("os.listdir", return_value=["12345"]), \
         patch("builtins.open", mock_open(read_data="agy --print")), \
         patch("app.database.get_latest_agent_activity_timestamp", return_value=recent_mtime):
        is_maint, reason = check_maintenance_status(db_session)
        assert is_maint is True
        assert "Active AI coding agent" in reason

def test_internal_monitorbot_ai_call_ignored(db_session):
    recent_mtime = time.time() - 10
    set_internal_ai_context(True)
    try:
        with patch("os.listdir", return_value=["12345"]), \
             patch("builtins.open", mock_open(read_data="agy --print")), \
             patch("app.database.get_latest_agent_activity_timestamp", return_value=recent_mtime):
            is_maint, reason = check_maintenance_status(db_session)
            assert is_maint is False
    finally:
        clear_internal_ai_context()

def test_internal_ai_context_manager(db_session):
    recent_mtime = time.time() - 10
    assert is_internal_ai_context() is False
    with internal_ai_context():
        assert is_internal_ai_context() is True
        with patch("os.listdir", return_value=["12345"]), \
             patch("builtins.open", mock_open(read_data="agy --print")), \
             patch("app.database.get_latest_agent_activity_timestamp", return_value=recent_mtime):
            is_maint, reason = check_maintenance_status(db_session)
            assert is_maint is False
    assert is_internal_ai_context() is False

def test_stack_audit_model_persists(db_session):
    audit = StackAudit(
        id="test-audit-1",
        stack_name="smarthome_core",
        status="HEALTHY",
        summary="All containers healthy",
        error_count="0",
        containers_checked="5",
    )
    db_session.add(audit)
    db_session.commit()
    fetched = db_session.query(StackAudit).filter(StackAudit.id == "test-audit-1").first()
    assert fetched is not None
    assert fetched.stack_name == "smarthome_core"
    assert fetched.status == "HEALTHY"
    assert fetched.summary == "All containers healthy"
    assert fetched.error_count == "0"
    assert fetched.containers_checked == "5"
    assert fetched.created_at is not None

def test_incident_stack_name_and_origin_fields(db_session):
    target = Target(id="homeassistant")
    db_session.add(target)
    db_session.commit()

    incident = Incident(
        id="inc-sre-test-1",
        target_id="homeassistant",
        stack_name="smarthome_core",
        origin="sre_daily_audit",
        status="PENDING_USER",
    )
    db_session.add(incident)
    db_session.commit()

    fetched = db_session.query(Incident).filter(Incident.id == "inc-sre-test-1").first()
    assert fetched is not None
    assert fetched.stack_name == "smarthome_core"
    assert fetched.origin == "sre_daily_audit"

def test_get_latest_agent_activity_timestamp_with_lock(tmp_path):
    lock_file = "/tmp/monitorbot_active_lock"
    with patch("os.path.exists") as mock_exists, \
         patch("os.path.getmtime") as mock_mtime, \
         patch("os.walk") as mock_walk:
        
        def exists_side_effect(path):
            if path == lock_file:
                return True
            return False

        mock_exists.side_effect = exists_side_effect
        mock_mtime.return_value = 1234567.0
        mock_walk.return_value = []

        ts = get_latest_agent_activity_timestamp()
        assert ts == 1234567.0

def test_get_latest_agent_activity_timestamp_with_walk(tmp_path):
    mock_file = tmp_path / "transcript.jsonl"
    mock_file.write_text("{}")
    target_mtime = time.time() - 100
    os.utime(str(mock_file), (target_mtime, target_mtime))

    with patch("os.path.exists") as mock_exists, \
         patch("os.walk") as mock_walk:
        mock_exists.return_value = True
        mock_walk.return_value = [
            (str(tmp_path), [], ["transcript.jsonl"])
        ]
        ts = get_latest_agent_activity_timestamp()
        assert abs(ts - target_mtime) < 1.0
