import pytest
from unittest.mock import patch, MagicMock
from app.watcher import run_watcher
from app.remediator import run_remediation
from app.database import Incident, Target

def test_watcher_events_stream_generator():
    mock_events = [
        {"Action": "die", "Actor": {"Attributes": {"name": "caddy"}}},  # Excluded
        {"Action": "die", "Actor": {"Attributes": {"name": "app1", "exitCode": "0", "com.docker.compose.project": "media"}}},  # Code 0
        {"Action": "die", "Actor": {"Attributes": {"name": "app2", "exitCode": "1", "com.docker.compose.project": "media"}}, "id": "app2-id"},  # Code 1 -> process_failure
        {"Action": "health_status: unhealthy", "Actor": {"Attributes": {"name": "app3", "com.docker.compose.project": "media"}}, "id": "app3-id"},  # Unhealthy -> process_failure
    ]
    
    mock_client = MagicMock()
    mock_client.events.side_effect = [mock_events, KeyboardInterrupt("Stop loop")]
    
    with patch("docker.from_env", return_value=mock_client), \
         patch("app.watcher.process_failure") as mock_proc:
        try:
            run_watcher()
        except KeyboardInterrupt:
            pass
        
        assert mock_proc.call_count == 2

@patch("subprocess.run")
@patch("app.remediator.time.sleep", return_value=None)
@patch("time.sleep", return_value=None)
@patch("docker.from_env")
def test_remediator_systemd_target(mock_docker, mock_sleep1, mock_sleep2, mock_run, db_session):
    target = Target(id="ssh_service", type="systemd")
    db_session.add(target)
    
    inc = Incident(id="inc-systemd-remedy", target_id="ssh_service", status="PENDING_USER", proposed_fix="systemctl restart ssh_service")
    db_session.add(inc)
    db_session.commit()
    
    mock_run.return_value = MagicMock(returncode=0, stdout="Restarted")
    
    with patch("app.remediator.send_followup_notification"), \
         patch("app.qdrant_mem.qdrant_mem.learn_incident"):
        run_remediation("inc-systemd-remedy")
        db_session.refresh(inc)
        assert inc.status == "RESOLVED"
