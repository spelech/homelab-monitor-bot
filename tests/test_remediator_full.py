import pytest
from unittest.mock import patch, MagicMock
from app.remediator import run_remediation
from app.database import Incident, Target

def test_remediator_blocks_dangerous_commands(db_session):
    target = Target(id="danger_target", type="docker")
    db_session.add(target)
    
    # 1. rm -rf
    inc1 = Incident(id="inc-danger-1", target_id="danger_target", status="PENDING_USER", proposed_fix="rm -rf /containers/media")
    # 2. docker system prune
    inc2 = Incident(id="inc-danger-2", target_id="danger_target", status="PENDING_USER", proposed_fix="docker system prune -a")
    # 3. reboot
    inc3 = Incident(id="inc-danger-3", target_id="danger_target", status="PENDING_USER", proposed_fix="sudo reboot")
    
    db_session.add_all([inc1, inc2, inc3])
    db_session.commit()
    
    with patch("app.remediator.send_followup_notification"):
        run_remediation("inc-danger-1")
        run_remediation("inc-danger-2")
        run_remediation("inc-danger-3")
        
        db_session.refresh(inc1)
        db_session.refresh(inc2)
        db_session.refresh(inc3)
        
        assert inc1.status == "BLOCKED"
        assert inc2.status == "BLOCKED"
        assert inc3.status == "BLOCKED"

def test_remediator_pauses_on_parent_dependency_incident(db_session):
    target = Target(id="child_app", type="docker")
    parent = Target(id="parent_db", type="docker")
    db_session.add_all([target, parent])
    
    inc_parent = Incident(id="inc-parent-active", target_id="parent_db", status="DETECTED")
    inc_child = Incident(id="inc-child-remedy", target_id="child_app", status="PENDING_USER", proposed_fix="docker restart child_app")
    db_session.add_all([inc_parent, inc_child])
    db_session.commit()
    
    with patch("app.dependencies.check_parent_incidents", return_value=[inc_parent]):
        run_remediation("inc-child-remedy")
        db_session.refresh(inc_child)
        assert inc_child.status == "PENDING_USER"
        assert "Unresolved parent dependencies" in inc_child.execution_log

@patch("subprocess.run")
@patch("app.remediator.time.sleep", return_value=None)
@patch("docker.from_env")
def test_remediator_execution_success(mock_docker, mock_sleep, mock_run, db_session):
    target = Target(id="safe_app", type="docker")
    db_session.add(target)
    
    inc = Incident(id="inc-safe-exec", target_id="safe_app", status="PENDING_USER", proposed_fix="docker restart safe_app")
    db_session.add(inc)
    db_session.commit()
    
    mock_run.return_value = MagicMock(returncode=0, stdout="Container restarted", stderr="")
    
    mock_container = MagicMock()
    mock_container.labels = {}
    mock_container.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
    mock_docker_client = MagicMock()
    mock_docker_client.containers.get.return_value = mock_container
    mock_docker.return_value = mock_docker_client
    
    with patch("app.remediator.send_followup_notification") as mock_notify, \
         patch("app.qdrant_mem.qdrant_mem.learn_incident"):
        
        run_remediation("inc-safe-exec")
        db_session.refresh(inc)
        assert inc.status == "RESOLVED"
        assert inc.completed_at is not None
        mock_notify.assert_called_once()
