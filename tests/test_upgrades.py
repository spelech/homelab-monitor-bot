import os
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.upgrades import UpgradeJob, UpgradeManager, upgrades_manager
from app.database import SessionLocal, UpgradeRun, Incident

client = TestClient(app)

def test_upgrade_job_lifecycle():
    job = UpgradeJob("run-test-1", ["media", "ai"])
    assert job.status == "RUNNING"
    assert job.current_step == "Initializing"
    
    job.append_log("Testing log line 1")
    job.append_log("Testing log line 2")
    
    d = job.to_dict()
    assert d["run_id"] == "run-test-1"
    assert len(d["logs"]) == 2
    assert "Testing log line 1" in d["logs"][0]

def test_get_stack_order_fallback(monkeypatch):
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    order = UpgradeManager.get_stack_order()
    assert "network" in order
    assert "webservices" in order

def test_get_stack_order_from_file(tmp_path, monkeypatch):
    conf = tmp_path / "stack_order.conf"
    conf.write_text('STACK_ORDER=(\n  "alpha"\n  "beta"\n)\n')
    
    monkeypatch.setattr(os.path, "exists", lambda p: p == "/containers/scripts/stack_order.conf")
    
    with patch("builtins.open", MagicMock(return_value=open(conf, "r"))):
        order = UpgradeManager.get_stack_order()
        assert "alpha" in order
        assert "beta" in order

def test_discover_stacks(monkeypatch):
    stacks = upgrades_manager.discover_stacks()
    assert isinstance(stacks, list)
    if stacks:
        assert "name" in stacks[0]
        assert "services_count" in stacks[0]

@patch("subprocess.run")
def test_run_canary_audit_all_pass(mock_run):
    # Mock all 4 subprocess calls
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="", stderr=""),  # restarting
        MagicMock(returncode=0, stdout="", stderr=""),  # unhealthy
        MagicMock(returncode=0, stdout="", stderr=""),  # caddy validate
        MagicMock(returncode=0, stdout="200", stderr="")  # curl
    ]
    
    res = upgrades_manager.run_canary_audit()
    assert res["overall_status"] == "PASS"
    assert res["failures_count"] == 0
    assert len(res["checks"]) == 4

@patch("subprocess.run")
def test_run_canary_audit_with_failures(mock_run):
    # Mock failure in restarting and caddy
    mock_run.side_effect = [
        MagicMock(returncode=0, stdout="container_crashing", stderr=""),  # restarting
        MagicMock(returncode=0, stdout="container_unhealthy", stderr=""),  # unhealthy
        MagicMock(returncode=1, stdout="", stderr="Validation error"),  # caddy validate
        MagicMock(returncode=0, stdout="502", stderr="")  # curl 502
    ]
    
    res = upgrades_manager.run_canary_audit()
    assert res["overall_status"] == "FAIL"
    assert res["failures_count"] == 4

@patch("subprocess.run")
def test_run_canary_audit_exception_handling(mock_run):
    mock_run.side_effect = Exception("Docker daemon unavailable")
    res = upgrades_manager.run_canary_audit()
    assert res["overall_status"] == "PASS"  # checks record ERROR status

def test_start_upgrade_errors(monkeypatch):
    monkeypatch.setattr(upgrades_manager, "discover_stacks", lambda: [{"name": "media"}])
    
    # Empty/invalid targets
    res = upgrades_manager.start_upgrade(["nonexistent_stack"])
    assert res["status"] == "error"
    
    # Already running job
    upgrades_manager.active_job = UpgradeJob("active-1", ["media"])
    upgrades_manager.active_job.status = "RUNNING"
    res2 = upgrades_manager.start_upgrade(["media"])
    assert res2["status"] == "error"
    assert "already running" in res2["message"]
    upgrades_manager.active_job = None

@patch("subprocess.run")
@patch("time.sleep", return_value=None)
def test_upgrade_workflow_execution(mock_sleep, mock_run, db_session):
    # Mock discovery
    with patch.object(upgrades_manager, "discover_stacks", return_value=[{"name": "test_stack"}]):
        mock_run.return_value = MagicMock(returncode=0, stdout="Success\nDone", stderr="")
        
        job = UpgradeJob("test-run-wf", ["test_stack"])
        
        # Mock canary to return pass
        with patch.object(upgrades_manager, "run_canary_audit", return_value={"overall_status": "PASS", "checks": [], "failures_count": 0}):
            upgrades_manager._run_upgrade_workflow(job)
            
            assert job.status == "SUCCESS"
            assert "ALL SYSTEMS HEALTHY" in "\n".join(job.logs)

@patch("subprocess.run")
@patch("time.sleep", return_value=None)
def test_upgrade_workflow_canary_failure_triggers_investigation(mock_sleep, mock_run, db_session):
    job = UpgradeJob("test-run-fail", ["test_stack"])
    mock_run.return_value = MagicMock(returncode=0, stdout="Pulled", stderr="")
    
    canary_fail = {
        "overall_status": "FAIL",
        "failures_count": 1,
        "checks": [
            {"name": "Restarting Containers", "status": "FAIL", "detail": "Containers in crashloop: test_failed_container"}
        ]
    }
    
    with patch.object(upgrades_manager, "run_canary_audit", return_value=canary_fail), \
         patch("app.investigator.trigger_investigation") as mock_investigate:
        
        upgrades_manager._run_upgrade_workflow(job)
        assert job.status == "WARNING"
        mock_investigate.assert_called_once()

def test_cancel_upgrade_and_status():
    upgrades_manager.active_job = UpgradeJob("job-cancel", ["stack1"])
    assert upgrades_manager.get_live_status() is not None
    
    res = upgrades_manager.cancel_active_upgrade()
    assert res["status"] == "cancelling"
    assert upgrades_manager.active_job.cancelled is True
    
    upgrades_manager.active_job = None
    assert upgrades_manager.cancel_active_upgrade()["status"] == "no_active_job"
    assert upgrades_manager.get_live_status() is None

def test_router_upgrades_endpoints(monkeypatch):
    # Test GET /api/upgrades/live when idle
    upgrades_manager.active_job = None
    res = client.get("/api/upgrades/live")
    assert res.status_code == 200
    assert res.json()["status"] == "IDLE"
    
    # Test GET /api/upgrades/runs/{run_id} 404
    res_404 = client.get("/api/upgrades/runs/nonexistent-run")
    assert res_404.status_code == 404
    
    # Test POST /api/upgrades/cancel
    res_cancel = client.post("/api/upgrades/cancel")
    assert res_cancel.status_code == 200
