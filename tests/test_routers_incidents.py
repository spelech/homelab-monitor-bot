import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.database import Incident, Target

client = TestClient(app)

def test_incidents_active_and_history(db_session):
    target = Target(id="active-service", type="docker")
    db_session.add(target)
    
    inc1 = Incident(id="inc-act-1", target_id="active-service", status="DETECTED")
    inc2 = Incident(id="inc-hist-1", target_id="active-service", status="RESOLVED")
    db_session.add(inc1)
    db_session.add(inc2)
    db_session.commit()
    
    res_act = client.get("/api/incidents/active")
    assert res_act.status_code == 200
    act_ids = [i["id"] for i in res_act.json()]
    assert "inc-act-1" in act_ids
    assert "inc-hist-1" not in act_ids
    
    res_hist = client.get("/api/incidents/history")
    assert res_hist.status_code == 200
    hist_ids = [i["id"] for i in res_hist.json()]
    assert "inc-hist-1" in hist_ids

def test_incident_actions(db_session):
    target = Target(id="act-target", type="docker")
    db_session.add(target)
    inc = Incident(
        id="inc-action-test",
        target_id="act-target",
        status="PENDING_USER",
        proposed_fix="docker restart act-target"
    )
    db_session.add(inc)
    db_session.commit()
    
    # Test 404
    res_404 = client.post("/api/incidents/nonexistent/action", json={"action": "defer"})
    assert res_404.status_code == 404
    
    # Test invalid action
    res_bad = client.post("/api/incidents/inc-action-test/action", json={"action": "invalid_action"})
    assert res_bad.status_code == 400
    
    # Test defer
    res_def = client.post("/api/incidents/inc-action-test/action", json={"action": "defer"})
    assert res_def.status_code == 200
    db_session.refresh(inc)
    assert inc.status == "DEFERRED"
    assert inc.deferred_until is not None
    
    # Test ignore
    res_ign = client.post("/api/incidents/inc-action-test/action", json={"action": "ignore"})
    assert res_ign.status_code == 200
    db_session.refresh(inc)
    assert inc.status == "IGNORED"
    
    # Test dismiss
    res_dis = client.post("/api/incidents/inc-action-test/action", json={"action": "dismiss"})
    assert res_dis.status_code == 200
    db_session.refresh(inc)
    assert inc.status == "RESOLVED"
    
    # Test fix with patched run_remediation
    inc.status = "PENDING_USER"
    inc.proposed_fix = "docker restart act-target"
    db_session.commit()
    with patch("app.routers.incidents.run_remediation"):
        res_fix = client.post("/api/incidents/inc-action-test/action", json={"action": "fix"})
        assert res_fix.status_code == 200
        db_session.refresh(inc)
        assert inc.status == "FIXING"

def test_targets_fleet_and_unignore(db_session):
    target = Target(id="target-fleet-1", type="docker", ignored_until=datetime.utcnow() + timedelta(days=1))
    db_session.add(target)
    db_session.commit()
    
    res = client.get("/api/targets")
    assert res.status_code == 200
    items = res.json()
    assert any(t["id"] == "target-fleet-1" and t["is_ignored"] is True for t in items)
    
    # Unignore 404
    res_404 = client.post("/api/targets/nonexistent/unignore")
    assert res_404.status_code == 404
    
    # Unignore 200
    res_unign = client.post("/api/targets/target-fleet-1/unignore")
    assert res_unign.status_code == 200
    db_session.refresh(target)
    assert target.ignored_until is None

def test_incidents_search_empty(monkeypatch):
    with patch("app.qdrant_mem.qdrant_mem.semantic_search", return_value=[]):
        res = client.get("/api/incidents/search?q=test")
        assert res.status_code == 200
        assert res.json() == []
