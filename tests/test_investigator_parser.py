import pytest
from unittest.mock import patch, MagicMock
from app.database import Incident, Target
from app.investigator import trigger_investigation

def test_trigger_investigation_success(db_session):
    # Setup target and incident in the test database
    target = Target(id="test-target", type="docker")
    db_session.add(target)
    db_session.commit()

    incident = Incident(
        id="test-incident-uuid",
        target_id="test-target",
        status="DETECTED",
        error_logs="Logs showing some database connection error."
    )
    db_session.add(incident)
    db_session.commit()

    # Mock subprocess.run to return a JSON block wrapped in markdown styling
    mock_stdout = """
Some random debug warnings...
```json
{
  "root_cause": "Database connection string had a typo.",
  "proposed_fix": "docker restart postgres-db",
  "category": "database"
}
```
Footnotes here.
"""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = mock_stdout

    with patch("subprocess.run", return_value=mock_result), \
         patch("app.notifier.send_incident_notification") as mock_notify:
        
        trigger_investigation("test-incident-uuid")
        
        # Verify db updates
        db_session.expire_all()
        updated_incident = db_session.query(Incident).filter(Incident.id == "test-incident-uuid").first()
        
        assert updated_incident.status == "PENDING_USER"
        assert updated_incident.root_cause == "Database connection string had a typo."
        assert updated_incident.proposed_fix == "docker restart postgres-db"
        assert updated_incident.category == "database"
        
        # Verify notification was triggered
        mock_notify.assert_called_once_with("test-incident-uuid")

def test_trigger_investigation_failure(db_session):
    # Setup target and incident in the test database
    target = Target(id="test-target", type="docker")
    db_session.add(target)
    db_session.commit()

    incident = Incident(
        id="test-incident-failed",
        target_id="test-target",
        status="DETECTED",
        error_logs="Logs showing failure."
    )
    db_session.add(incident)
    db_session.commit()

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "agy binary execution crashed."

    with patch("subprocess.run", return_value=mock_result), \
         patch("app.notifier.send_incident_notification") as mock_notify:
        
        trigger_investigation("test-incident-failed")
        
        db_session.expire_all()
        updated_incident = db_session.query(Incident).filter(Incident.id == "test-incident-failed").first()
        
        assert updated_incident.status == "FAILED"
        assert "agy error" in updated_incident.execution_log
        mock_notify.assert_not_called()
