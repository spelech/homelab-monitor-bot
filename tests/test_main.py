"""
tests/test_main.py
~~~~~~~~~~~~~~~~~~
Unit tests for webhook routes and the container health auto-resolve pre-check.
"""
import os
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.database import Incident, Target

client = TestClient(app)
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "test_secret_token")

@pytest.fixture(autouse=True)
def mock_webhook_token():
    with patch("app.main.WEBHOOK_TOKEN", WEBHOOK_TOKEN):
        yield

def test_webhook_unauthorized():
    response = client.post(
        f"/api/webhooks/some-id?token=invalid_token",
        json={"action": "fix"}
    )
    assert response.status_code == 401

def test_webhook_incident_not_found():
    response = client.post(
        f"/api/webhooks/non-existent-uuid?token={WEBHOOK_TOKEN}",
        json={"action": "fix"}
    )
    assert response.status_code == 404

def test_webhook_idempotent_skips(db_session):
    target = Target(id="test-target-id", type="docker")
    db_session.add(target)
    incident = Incident(id="inc-idempotent", target_id="test-target-id", status="RESOLVED")
    db_session.add(incident)
    db_session.commit()

    response = client.post(
        f"/api/webhooks/inc-idempotent?token={WEBHOOK_TOKEN}",
        json={"action": "fix"}
    )
    assert response.status_code == 200
    assert "Already processed in state RESOLVED" in response.json()["detail"]

@patch("app.main.send_followup_notification")
@patch("docker.from_env")
def test_webhook_auto_resolves_when_healthy(mock_docker, mock_notify, db_session):
    # Setup database state
    target = Target(id="healthy-service", type="docker")
    db_session.add(target)
    incident = Incident(id="inc-healthy-precheck", target_id="healthy-service", status="PENDING_USER")
    db_session.add(incident)
    db_session.commit()

    # Mock docker container to report healthy and running
    mock_container = MagicMock()
    mock_container.attrs = {
        "State": {
            "Running": True,
            "Health": {"Status": "healthy"}
        }
    }
    mock_docker_client = MagicMock()
    mock_docker_client.containers.get.return_value = mock_container
    mock_docker.return_value = mock_docker_client

    response = client.post(
        f"/api/webhooks/inc-healthy-precheck?token={WEBHOOK_TOKEN}",
        json={"action": "fix"}
    )
    assert response.status_code == 200
    assert "already resolved without action" in response.json()["detail"]

    # Verify db status was updated to RESOLVED
    db_session.expire_all()
    inc = db_session.query(Incident).filter_by(id="inc-healthy-precheck").first()
    assert inc.status == "RESOLVED"
    assert "Target was already healthy" in inc.execution_log
    
    # Assert notification was triggered
    mock_notify.assert_called_once()
    assert "resolved automatically without action" in mock_notify.call_args[0][1]

@patch("app.main.run_remediation")
@patch("docker.from_env")
def test_webhook_proceeds_when_unhealthy(mock_docker, mock_remedy, db_session):
    target = Target(id="unhealthy-service", type="docker")
    db_session.add(target)
    incident = Incident(id="inc-unhealthy-precheck", target_id="unhealthy-service", status="PENDING_USER")
    db_session.add(incident)
    db_session.commit()

    # Mock docker container to report unhealthy/exited
    mock_container = MagicMock()
    mock_container.attrs = {
        "State": {
            "Running": False,
            "Status": "exited"
        }
    }
    mock_docker_client = MagicMock()
    mock_docker_client.containers.get.return_value = mock_container
    mock_docker.return_value = mock_docker_client

    response = client.post(
        f"/api/webhooks/inc-unhealthy-precheck?token={WEBHOOK_TOKEN}",
        json={"action": "fix"}
    )
    assert response.status_code == 200
    assert response.json()["detail"] == "Remediation triggered"

    # Verify db status was updated to FIXING
    db_session.expire_all()
    inc = db_session.query(Incident).filter_by(id="inc-unhealthy-precheck").first()
    assert inc.status == "FIXING"
    
    # Assert remediation worker was triggered
    mock_remedy.assert_called_once_with("inc-unhealthy-precheck")
