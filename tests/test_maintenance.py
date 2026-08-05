from datetime import datetime, timedelta
from unittest.mock import patch
from app.database import init_db, set_setting, get_setting, check_maintenance_status

def test_maintenance_mode_init_db(db_session):
    init_db()
    val = get_setting("maintenance_mode")
    assert val == "false"

def test_check_maintenance_status_manual_indefinite(db_session):
    set_setting("maintenance_mode", "indefinite")
    with patch("os.path.exists", return_value=False):
        is_maint, reason = check_maintenance_status(db_session)
        assert is_maint is True
        assert "Manual maintenance (indefinite)" in reason

def test_check_maintenance_status_manual_timestamp_active(db_session):
    future_dt = (datetime.utcnow() + timedelta(minutes=30)).isoformat() + "Z"
    set_setting("maintenance_mode", future_dt)
    with patch("os.path.exists", return_value=False):
        is_maint, reason = check_maintenance_status(db_session)
        assert is_maint is True
        assert "Manual maintenance" in reason
        assert "remaining" in reason

def test_check_maintenance_status_manual_timestamp_expired(db_session):
    past_dt = (datetime.utcnow() - timedelta(minutes=30)).isoformat() + "Z"
    set_setting("maintenance_mode", past_dt)
    with patch("os.path.exists", return_value=False):
        is_maint, reason = check_maintenance_status(db_session)
        assert is_maint is False
        assert reason == ""

def test_check_maintenance_status_active_update_script(db_session):
    set_setting("maintenance_mode", "false")
    fake_cmdline = "/bin/bash ./update_all.sh"
    
    with patch("os.path.exists", return_value=True), \
         patch("os.listdir", return_value=["1234"]), \
         patch("builtins.open") as mock_open:
        
        # We need mock file reads for /proc/1234/status and /proc/1234/cmdline
        def mock_open_side_effect(filepath, *args, **kwargs):
            from unittest.mock import mock_open as m_open
            if "status" in str(filepath):
                return m_open(read_data="PPid: 1\n")()
            elif "cmdline" in str(filepath):
                return m_open(read_data=fake_cmdline + "\x00")()
            raise FileNotFoundError(filepath)

        mock_open.side_effect = mock_open_side_effect

        is_maint, reason = check_maintenance_status(db_session)
        assert is_maint is True
        assert "Active update script" in reason

def test_process_failure_suppressed_during_maintenance(db_session):
    from unittest.mock import MagicMock
    from app.watcher import process_failure
    from app.database import Incident

    set_setting("maintenance_mode", "indefinite")
    mock_docker = MagicMock()
    
    with patch("os.path.exists", return_value=False):
        process_failure(mock_docker, "target_app", "mock_id_456", "Container died")

    inc = db_session.query(Incident).filter(Incident.target_id == "target_app").first()
    assert inc is None

def test_api_maintenance_modes(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_setting

    client = TestClient(app)

    # 1. Test indefinite pause
    resp = client.post("/api/maintenance", json={"duration": "indefinite"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert get_setting("maintenance_mode") == "indefinite"

    # 2. Test resume
    resp = client.post("/api/maintenance", json={"duration": "resume"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert get_setting("maintenance_mode") == "false"

    # 3. Test timed pause (e.g. 15m)
    resp = client.post("/api/maintenance", json={"duration": "15m"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert get_setting("maintenance_mode") != "false"
    assert get_setting("maintenance_mode") != "indefinite"
    assert "Z" in get_setting("maintenance_mode")

    # 4. Test invalid duration
    resp = client.post("/api/maintenance", json={"duration": "invalid"})
    assert resp.status_code == 400

def test_api_settings_maintenance(db_session):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import set_setting

    client = TestClient(app)

    # Set non-maintenance state
    set_setting("maintenance_mode", "false")
    with patch("os.path.exists", return_value=False):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["maintenance_active"] is False
        assert data["maintenance_mode"] == "false"

    # Set indefinite maintenance
    set_setting("maintenance_mode", "indefinite")
    with patch("os.path.exists", return_value=False):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["maintenance_active"] is True
        assert data["maintenance_mode"] == "indefinite"
        assert "indefinite" in data["maintenance_reason"]

def test_cli_pause_and_resume(db_session, capsys):
    import sys
    import pytest
    from cli import main

    # Test pause default (indefinite)
    with patch.object(sys, "argv", ["cli.py", "pause"]):
        main()
    out = capsys.readouterr().out
    assert "Maintenance Mode ENABLED indefinitely" in out
    assert get_setting("maintenance_mode") == "indefinite"

    # Test status during maintenance
    with patch.object(sys, "argv", ["cli.py", "status"]), patch("os.path.exists", return_value=False):
        main()
    out = capsys.readouterr().out
    assert "Maintenance Mode:              ACTIVE" in out

    # Test resume
    with patch.object(sys, "argv", ["cli.py", "resume"]):
        main()
    out = capsys.readouterr().out
    assert "Maintenance Mode DISABLED" in out
    assert get_setting("maintenance_mode") == "false"

    # Test timed pause (30m)
    with patch.object(sys, "argv", ["cli.py", "pause", "30m"]):
        main()
    out = capsys.readouterr().out
    assert "Maintenance Mode ENABLED until" in out
    assert "30m" in out
    assert get_setting("maintenance_mode") != "false"

    # Test invalid duration
    with patch.object(sys, "argv", ["cli.py", "pause", "invalid_fmt"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Error: Invalid duration format" in out




