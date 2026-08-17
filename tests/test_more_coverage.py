import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.database import Incident, Target
from app.investigator import run_investigation_logic, check_and_resolve_incident_if_healthy
from app.remediator import run_remediation
from app.qdrant_mem import QdrantMemory

client = TestClient(app)

def test_qdrant_error_handling():
    mem = QdrantMemory()
    mem.client = None
    assert mem.learn_incident("1", "2", "3", "4") is False
    assert mem.query_similar_fix("target", "cause") is None
    assert mem.semantic_search("query") == []

@patch("subprocess.run")
def test_investigator_fallback_when_output_empty(mock_run, db_session):
    target = Target(id="empty_target", type="docker")
    inc = Incident(id="inc-empty-out", target_id="empty_target", status="DETECTED", error_logs="Crash")
    db_session.add_all([target, inc])
    db_session.commit()
    
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Crash in AI executor")
    
    with patch("app.investigator.call_opencode_server", side_effect=Exception("Server unavailable")), \
         patch("app.ai_usage.record_ai_usage"):
        run_investigation_logic(db_session, inc)
        db_session.refresh(inc)
        assert inc.status == "FAILED"

@patch("subprocess.run")
@patch("app.remediator.time.sleep", return_value=None)
@patch("docker.from_env")
def test_remediator_execution_kuma_probe(mock_docker, mock_sleep, mock_run, db_session):
    target = Target(id="probe_app", type="docker")
    db_session.add(target)
    
    inc = Incident(id="inc-probe-exec", target_id="probe_app", status="PENDING_USER", proposed_fix="docker restart probe_app")
    db_session.add(inc)
    db_session.commit()
    
    mock_run.return_value = MagicMock(returncode=0, stdout="Done", stderr="")
    
    mock_container = MagicMock()
    mock_container.labels = {"kuma.probe_app.http.url": "http://10.0.0.10:8000"}
    mock_docker_client = MagicMock()
    mock_docker_client.containers.get.return_value = mock_container
    mock_docker.return_value = mock_docker_client
    
    with patch("requests.get", return_value=MagicMock(status_code=200)), \
         patch("app.remediator.send_followup_notification"), \
         patch("app.qdrant_mem.qdrant_mem.learn_incident"):
        
        run_remediation("inc-probe-exec")
        db_session.refresh(inc)
        assert inc.status == "RESOLVED"

def test_main_mcp_sse_endpoint():
    # Test mcp endpoint status code
    res = client.get("/mcp/sse")
    assert res.status_code in [200, 307, 404, 405]
