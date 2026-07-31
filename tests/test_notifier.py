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

    with patch("requests.post", side_effect=Exception("Connection timed out")) as mock_requests_post, \
         patch("app.notifier.send_email_notification", return_value=True) as mock_send_email:
        
        with patch.dict(os.environ, {
            "NTFY_URL": "https://ntfy.unreachable-test.com",
            "NTFY_TOPIC": "alerts",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": ""
        }):
            send_incident_notification("test-notifier-uuid")
            
            # Primary NTFY was attempted
            assert mock_requests_post.call_count >= 1
            first_url = mock_requests_post.call_args_list[0][0][0]
            assert "unreachable-test" in first_url

            # Direct fallback to email was triggered
            mock_send_email.assert_called_once()
            assert "test-notifier-target failure" in mock_send_email.call_args[0][0]


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


def test_send_heartbeat_notification():
    from app.notifier import send_heartbeat_notification

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("requests.post", return_value=mock_resp) as mock_post:
        with patch.dict(os.environ, {
            "NTFY_URL": "https://ntfy.wileyriley.com",
            "NTFY_TOPIC": "alerts",
            "TELEGRAM_BOT_TOKEN": "12345:token",
            "TELEGRAM_CHAT_ID": "67890"
        }):
            send_heartbeat_notification()
            
            # Should call Telegram and then ntfy
            assert mock_post.call_count == 2
            urls = [call[0][0] for call in mock_post.call_args_list]
            assert "https://api.telegram.org/bot12345:token/sendMessage" in urls
            assert "https://ntfy.wileyriley.com/alerts" in urls

