import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.ai_usage import record_ai_usage, calculate_cost, estimate_tokens_from_text

client = TestClient(app)

def test_token_and_cost_calculation():
    text = "Hello world this is a test investigation prompt."
    tokens = estimate_tokens_from_text(text)
    assert tokens > 0
    
    cost = calculate_cost("qwen3.5-flash-02-23", 1000, 500)
    assert cost > 0.0

def test_record_ai_usage_and_summary_endpoint():
    log = record_ai_usage(
        incident_id=None,
        executor="opencode",
        model_id="qwen3.5-flash-02-23",
        prompt_text="Test prompt text",
        completion_text="Test response text",
        prompt_tokens=100,
        completion_tokens=50,
        duration_sec=1.23,
        status="SUCCESS"
    )
    assert log is not None
    assert log.id is not None
    assert log.executor == "opencode"
    
    response = client.get("/api/usage/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_calls"] >= 1
    assert data["total_tokens"] >= 150
    assert "model_counts" in data
    assert "recent_logs" in data
