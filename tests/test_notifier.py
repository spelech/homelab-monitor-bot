import pytest
import os
from unittest.mock import patch, MagicMock
from app.notifier import safe_header, send_incident_notification, send_followup_notification
from app.database import Incident, Target

def test_safe_header_ascii():
    assert safe_header("Simple title") == "Simple title"

def test_safe_header_unicode():
    val = "🚨 AutoHeal Incident: test-container failure"
    encoded = safe_header(val)
    assert "=?utf-8?q?" in encoded
    # Ensure line folding is disabled (no return characters)
    assert "\n" not in encoded

def test_send_incident_notification_fallback(db_session):
    # Setup target and incident in the test database
    target = Target(id="test-notifier-target", type="docker")
    db_session.add(target)
    db_session.commit()

    incident = Incident(
        id="test-notifier-uuid",
        target_id="test-notifier-target",
        status="PENDING_USER",
        root_cause="Out of disk space.",
        proposed_fix="docker system prune -f"
    )
    db_session.add(incident)
    db_session.commit()

    # Mock requests.post to raise exception on primary and succeed on localhost fallback
    def mock_post(url, *args, **kwargs):
        resp = MagicMock()
        if "unreachable-test" in url or "wileyriley" in url:
            raise Exception("Connection timed out")
        else:
            resp.status_code = 200
            return resp

    with patch("requests.post", side_effect=mock_post) as mock_requests_post:
        # Mock configs using patch.dict
        with patch.dict(os.environ, {
            "NTFY_URL": "https://ntfy.unreachable-test.com",
            "NTFY_TOPIC": "alerts",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": ""
        }):
            send_incident_notification("test-notifier-uuid")
            
            # Verify primary was attempted, then fallback was attempted
            assert mock_requests_post.call_count >= 2
            
            first_url = mock_requests_post.call_args_list[0][0][0]
            assert "unreachable-test" in first_url
            
            second_url = mock_requests_post.call_args_list[1][0][0]
            assert "http://localhost:9010" in second_url
            
            # Check fallback action buttons header targets the local IP
            fallback_headers = mock_requests_post.call_args_list[1][1]["headers"]
            assert "Actions" in fallback_headers
            assert "http://10.0.0.10:9013" in fallback_headers["Actions"]

def test_send_telegram_invoked(db_session):
    target = Target(id="test-tg-target", type="docker")
    db_session.add(target)
    db_session.commit()

    incident = Incident(
        id="test-tg-uuid",
        target_id="test-tg-target",
        status="PENDING_USER",
        root_cause="Broken config.",
        proposed_fix="docker restart app"
    )
    db_session.add(incident)
    db_session.commit()

    # Mock requests.post to track telegram calls
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp) as mock_requests_post:
        with patch.dict(os.environ, {
            "NTFY_URL": "https://ntfy.unreachable-test.com",
            "NTFY_TOPIC": "alerts",
            "TELEGRAM_BOT_TOKEN": "123456:mock_token",
            "TELEGRAM_CHAT_ID": "987654321"
        }):
            send_incident_notification("test-tg-uuid")
            
            # Should call Telegram and then ntfy
            # 1. Telegram call, 2. ntfy primary call
            assert mock_requests_post.call_count >= 2
            
            # Check that Telegram API endpoint was one of the calls
            urls = [call[0][0] for call in mock_requests_post.call_args_list]
            assert "https://api.telegram.org/bot123456:mock_token/sendMessage" in urls
