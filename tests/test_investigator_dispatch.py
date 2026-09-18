import pytest
from unittest.mock import patch, MagicMock
import requests
from app.investigator import (
    call_ai_dispatch_server,
    AI_DISPATCH_URL,
    AI_MODEL,
    AI_DISPATCH_TIMEOUT,
)

def test_call_ai_dispatch_server_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "chatcmpl-123",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"root_cause": "test", "proposed_fix": "restart container"}'
                },
                "finish_reason": "stop"
            }
        ]
    }

    with patch("app.investigator.requests.post", return_value=mock_resp) as mock_post:
        content, duration = call_ai_dispatch_server(
            prompt="Investigate failure",
            model_id="opencode",
            timeout=60
        )

        assert content == '{"root_cause": "test", "proposed_fix": "restart container"}'
        assert isinstance(duration, float)
        assert duration >= 0.0

        mock_post.assert_called_once_with(
            f"{AI_DISPATCH_URL}/chat/completions",
            json={
                "model": "opencode",
                "messages": [{"role": "user", "content": "Investigate failure"}],
                "temperature": 0.2
            },
            timeout=60
        )

def test_call_ai_dispatch_server_empty_choices():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"choices": []}

    with patch("app.investigator.requests.post", return_value=mock_resp):
        with pytest.raises(ValueError, match="No choices returned from AI dispatch gateway"):
            call_ai_dispatch_server(prompt="Test empty")

def test_call_ai_dispatch_server_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Internal Server Error")

    with patch("app.investigator.requests.post", return_value=mock_resp):
        with pytest.raises(requests.exceptions.HTTPError):
            call_ai_dispatch_server(prompt="Investigate failure")
