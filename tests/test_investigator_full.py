import json
import pytest
from unittest.mock import patch, MagicMock
from app.investigator import (
    is_target_healthy,
    check_and_resolve_incident_if_healthy,
    cleanup_resolved_incidents,
    run_investigation_logic
)
from app.database import Incident, Target

def test_is_target_healthy_docker(monkeypatch):
    mock_container = MagicMock()
    mock_container.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
    mock_docker = MagicMock()
    mock_docker.containers.get.return_value = mock_container
    
    with patch("docker.from_env", return_value=mock_docker):
        assert is_target_healthy("target1", "docker") is True
        
        mock_container.attrs = {"State": {"Running": False}}
        assert is_target_healthy("target1", "docker") is False

def test_check_and_resolve_incident_if_healthy(db_session):
    target = Target(id="healthy_target", type="docker")
    inc = Incident(id="inc-health-check", target_id="healthy_target", status="DETECTED")
    db_session.add_all([target, inc])
    db_session.commit()
    
    with patch("app.investigator.is_target_healthy", return_value=True):
        resolved = check_and_resolve_incident_if_healthy(db_session, inc)
        assert resolved is True
        assert inc.status == "RESOLVED"
        assert inc.completed_at is not None

def test_cleanup_resolved_incidents(db_session):
    target = Target(id="clean_target", type="docker")
    inc = Incident(id="inc-cleanup-1", target_id="clean_target", status="INVESTIGATING")
    db_session.add_all([target, inc])
    db_session.commit()
    
    with patch("app.investigator.is_target_healthy", return_value=True):
        cleanup_resolved_incidents()
        db_session.refresh(inc)
        assert inc.status == "RESOLVED"

@patch("subprocess.run")
def test_run_investigation_logic_opencode_fallback(mock_run, db_session):
    target = Target(id="inv_target", type="docker")
    inc = Incident(id="inc-inv-1", target_id="inv_target", status="DETECTED", error_logs="Sample crash")
    db_session.add_all([target, inc])
    db_session.commit()
    
    ai_json = json.dumps({
        "root_cause": "Port conflict on 8080",
        "proposed_fix": "docker restart inv_target",
        "category": "network"
    })
    
    # Mock CLI subprocess output
    mock_run.return_value = MagicMock(returncode=0, stdout=ai_json, stderr="")
    
    with patch("app.investigator.call_opencode_server", side_effect=Exception("Server offline")), \
         patch("app.notifier.send_incident_notification") as mock_notify:
        
        run_investigation_logic(db_session, inc)
        
        db_session.refresh(inc)
        assert inc.status == "PENDING_USER"
        assert inc.root_cause == "Port conflict on 8080"
        assert inc.proposed_fix == "docker restart inv_target"
        assert inc.category == "network"
        mock_notify.assert_called_once()
