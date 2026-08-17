import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from app.watcher import process_failure
from app.database import Incident, Target

def test_process_failure_standard_flow(db_session):
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_container.logs.return_value = b"Error: Out of memory"
    mock_client.containers.get.return_value = mock_container
    
    with patch("app.database.check_maintenance_status", return_value=(False, "")), \
         patch("app.watcher.trigger_investigation") as mock_investigate:
        
        process_failure(mock_client, "test_target_proc", "c_id_123", "die non-zero exit")
        
        inc = db_session.query(Incident).filter(Incident.target_id == "test_target_proc").first()
        assert inc is not None
        assert inc.status == "DETECTED"
        assert "Out of memory" in inc.error_logs

def test_process_failure_maintenance_skips(db_session):
    mock_client = MagicMock()
    with patch("app.database.check_maintenance_status", return_value=(True, "Maintenance active")), \
         patch("app.watcher.trigger_investigation") as mock_investigate:
        
        process_failure(mock_client, "test_maint_target", "c_id_123", "die")
        
        inc = db_session.query(Incident).filter(Incident.target_id == "test_maint_target").first()
        assert inc is None
        mock_investigate.assert_not_called()

def test_process_failure_caddy_suppression(db_session):
    # Caddy has an active incident
    caddy_inc = Incident(id="inc-caddy-active", target_id="caddy", status="DETECTED")
    db_session.add(caddy_inc)
    db_session.commit()
    
    mock_client = MagicMock()
    with patch("app.database.check_maintenance_status", return_value=(False, "")), \
         patch("app.watcher.trigger_investigation") as mock_investigate:
        
        process_failure(mock_client, "downstream_app", "c_id_123", "die")
        
        inc = db_session.query(Incident).filter(Incident.target_id == "downstream_app").first()
        assert inc is None
        mock_investigate.assert_not_called()

def test_process_failure_circuit_breaker(db_session):
    target = Target(id="cb_target", type="docker")
    db_session.add(target)
    
    now = datetime.utcnow()
    inc1 = Incident(id="cb-inc-1", target_id="cb_target", status="FAILED", completed_at=now - timedelta(minutes=10))
    inc2 = Incident(id="cb-inc-2", target_id="cb_target", status="FAILED", completed_at=now - timedelta(minutes=5))
    db_session.add(inc1)
    db_session.add(inc2)
    db_session.commit()
    
    mock_client = MagicMock()
    with patch("app.database.check_maintenance_status", return_value=(False, "")), \
         patch("app.notifier.send_incident_notification") as mock_notify:
        
        process_failure(mock_client, "cb_target", "c_id_123", "die")
        
        blocked_inc = db_session.query(Incident).filter(Incident.target_id == "cb_target", Incident.status == "BLOCKED").first()
        assert blocked_inc is not None
        mock_notify.assert_called_once()
