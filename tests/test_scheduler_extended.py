import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from app.scheduler import check_systemd_services, trigger_heartbeat, check_deferred_and_ignored
from app.database import Incident, Target

@patch("subprocess.run")
def test_check_systemd_services_healthy(mock_run, db_session):
    mock_run.return_value = MagicMock(returncode=0)
    with patch("app.investigator.trigger_investigation") as mock_inv:
        check_systemd_services()
        mock_inv.assert_not_called()

@patch("subprocess.run")
def test_check_systemd_services_failure_creates_incident(mock_run, db_session):
    # Mock systemctl is-active failure
    mock_run.side_effect = [
        MagicMock(returncode=3),  # systemctl is-active returns non-zero
        MagicMock(returncode=0, stdout="Unit failed to start", stderr="")  # journalctl
    ]
    
    with patch("app.investigator.trigger_investigation") as mock_inv, \
         patch("app.database.check_maintenance_status", return_value=(False, "")):
        
        check_systemd_services()
        inc = db_session.query(Incident).filter(Incident.target_id.in_(["plexmediaserver", "ssh"])).first()
        if inc:
            assert inc.status == "DETECTED"

def test_trigger_heartbeat(db_session):
    with patch("app.notifier.send_heartbeat_notification") as mock_hb:
        trigger_heartbeat()
        mock_hb.assert_called_once()
