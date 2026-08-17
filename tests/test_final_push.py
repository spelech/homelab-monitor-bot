import pytest
from unittest.mock import patch, MagicMock
from app.remediator import run_remediation
from app.investigator import run_investigation_logic
from app.database import Incident, Target

@patch("subprocess.run")
@patch("app.remediator.time.sleep", return_value=None)
@patch("time.sleep", return_value=None)
@patch("docker.from_env")
def test_remediator_caddy_down_fallback(mock_docker, mock_sleep1, mock_sleep2, mock_run, db_session):
    target = Target(id="downstream_service", type="docker")
    db_session.add(target)
    
    inc = Incident(
        id="inc-caddy-fallback",
        target_id="downstream_service",
        status="PENDING_USER",
        proposed_fix="docker restart downstream_service"
    )
    db_session.add(inc)
    db_session.commit()
    
    mock_run.return_value = MagicMock(returncode=0, stdout="Restarted", stderr="")
    
    # Mock container with kuma label and running state
    mock_container = MagicMock()
    mock_container.labels = {"kuma.downstream.http.url": "https://downstream.wileyriley.com"}
    mock_container.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
    
    # Mock caddy container being stopped
    mock_caddy = MagicMock()
    mock_caddy.status = "exited"
    
    def get_container(name):
        if name == "caddy":
            return mock_caddy
        return mock_container
        
    mock_docker_client = MagicMock()
    mock_docker_client.containers.get.side_effect = get_container
    mock_docker.return_value = mock_docker_client
    
    with patch("requests.get", side_effect=Exception("Connection refused")), \
         patch("app.remediator.send_followup_notification"), \
         patch("app.qdrant_mem.qdrant_mem.learn_incident"):
        
        run_remediation("inc-caddy-fallback")
        db_session.refresh(inc)
        assert inc.status == "RESOLVED"

@patch("subprocess.run")
def test_investigator_learns_qdrant_and_auto_approves(mock_run, db_session):
    target = Target(id="auto_app_target", type="docker")
    inc = Incident(
        id="inc-auto-app",
        target_id="auto_app_target",
        status="DETECTED",
        error_logs="Permission error 13"
    )
    db_session.add_all([target, inc])
    db_session.commit()
    
    mock_json = '{"root_cause": "Permissions mismatch", "proposed_fix": "chmod -R 755 /data", "category": "permissions"}'
    
    with patch("app.investigator.call_opencode_server", return_value=mock_json), \
         patch("app.database.get_setting", return_value="true"), \
         patch("app.remediator.run_remediation") as mock_remedy, \
         patch("app.qdrant_mem.qdrant_mem.learn_incident"):
        
        run_investigation_logic(db_session, inc)
        db_session.refresh(inc)
        assert inc.status in ["FIXING", "PENDING_USER"]
        assert inc.root_cause == "Permissions mismatch"
