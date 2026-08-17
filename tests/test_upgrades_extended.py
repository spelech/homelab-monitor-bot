import json
import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.database import UpgradeRun
from app.upgrades import UpgradeJob, upgrades_manager

client = TestClient(app)

def test_api_upgrades_runs_list_and_detail(db_session):
    run = UpgradeRun(
        id="run-detail-123",
        status="SUCCESS",
        targets=json.dumps(["media", "books"]),
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        logs=json.dumps(["Step 1", "Step 2"]),
        canary_results=json.dumps({"overall_status": "PASS"})
    )
    db_session.add(run)
    db_session.commit()
    
    # Test GET /api/upgrades/runs
    res = client.get("/api/upgrades/runs")
    assert res.status_code == 200
    runs = res.json()
    assert any(r["id"] == "run-detail-123" for r in runs)
    
    # Test GET /api/upgrades/runs/{id}
    res_detail = client.get("/api/upgrades/runs/run-detail-123")
    assert res_detail.status_code == 200
    assert res_detail.json()["id"] == "run-detail-123"
    assert res_detail.json()["status"] == "SUCCESS"

def test_api_upgrades_canary_standalone():
    with patch.object(upgrades_manager, "run_canary_audit", return_value={"overall_status": "PASS", "checks": []}):
        res = client.post("/api/upgrades/canary")
        assert res.status_code == 200
        assert res.json()["overall_status"] == "PASS"

def test_api_upgrades_trigger_run():
    with patch.object(upgrades_manager, "start_upgrade", return_value={"status": "started", "run_id": "run-new-1"}):
        res = client.post("/api/upgrades/run", json={"targets": ["media"]})
        assert res.status_code == 200
        assert res.json()["status"] == "started"
        
    with patch.object(upgrades_manager, "start_upgrade", return_value={"status": "error", "message": "Already running"}):
        res_err = client.post("/api/upgrades/run", json={"targets": ["media"]})
        assert res_err.status_code == 400
