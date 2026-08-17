import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.database import Incident, Target

client = TestClient(app)

def test_api_dashboard_serialization(db_session):
    target = Target(id="dash-test", type="docker")
    db_session.add(target)
    
    inc = Incident(
        id="inc-dash-1",
        target_id="dash-test",
        status="DETECTED",
        category="network",
        root_cause="DNS timeout",
        proposed_fix="docker restart dash-test",
        created_at=datetime.utcnow()
    )
    db_session.add(inc)
    db_session.commit()
    
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    data = res.json()
    assert data["active_count"] >= 1
    assert any(i["id"] == "inc-dash-1" for i in data["active_incidents"])
    assert "maintenance_active" in data
    assert "autopilot" in data

def test_catch_all_spa_route():
    # Test valid non-api path
    res = client.get("/upgrades")
    assert res.status_code == 200
    
    # Test invalid api path returns 404
    res_api = client.get("/api/nonexistent_route")
    assert res_api.status_code == 404
