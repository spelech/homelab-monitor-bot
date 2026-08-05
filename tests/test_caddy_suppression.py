import pytest
from unittest.mock import patch, MagicMock
from app.database import Incident, Target
from app.watcher import process_failure

@patch("app.database.check_maintenance_status", return_value=(False, ""))
def test_caddy_cascading_suppression(mock_maint, db_session):
    # 1. Create an active Caddy incident
    caddy_target = Target(id="caddy", type="docker")
    db_session.add(caddy_target)
    caddy_incident = Incident(
        id="caddy_active_inc",
        target_id="caddy",
        status="DETECTED",
        error_logs="Caddyfile parse error"
    )
    db_session.add(caddy_incident)
    db_session.commit()

    # 2. Simulate a failure event on another container (e.g. librechat)
    mock_docker = MagicMock()
    process_failure(mock_docker, "librechat", "mock_id_123", "Container died")

    # 3. Assert that NO incident was created for librechat because Caddy has an active incident
    inc = db_session.query(Incident).filter(Incident.target_id == "librechat").first()
    assert inc is None
