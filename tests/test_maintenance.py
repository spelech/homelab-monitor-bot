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
