import os
import pytest
from unittest.mock import patch, MagicMock
from app.notifier import send_email_notification, send_incident_notification
from app.database import Incident

def test_send_email_notification_success():
    with patch("smtplib.SMTP") as mock_smtp:
        mock_instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_instance

        with patch.dict(os.environ, {
            "SMTP_SERVER": "smtp.gmail.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "test@example.com",
            "SMTP_PASS": "secret",
            "EMAIL_FROM": "test@example.com",
            "EMAIL_TO": "user@example.com"
        }):
            res = send_email_notification("Subject", "Body content")
            assert res is True
            mock_instance.starttls.assert_called_once()
            mock_instance.login.assert_called_once_with("test@example.com", "secret")
            mock_instance.send_message.assert_called_once()

def test_send_incident_notification_email_fallback(db_session):
    incident = Incident(
        id="test_email_fallback_inc",
        target_id="caddy",
        status="DETECTED",
        root_cause="Nginx/Caddy configuration syntax error causing all subdomains to 404",
        proposed_fix="Fix Caddyfile syntax and restart caddy"
    )
    db_session.add(incident)
    db_session.commit()


    with patch("requests.post") as mock_post, \
         patch("app.notifier.send_email_notification") as mock_send_email:
        
        # Simulate network error connecting to primary & local ntfy
        mock_post.side_effect = Exception("Connection refused / Network unreachable")
        mock_send_email.return_value = True

        send_incident_notification("test_email_fallback_inc")

        mock_send_email.assert_called_once()
        args, kwargs = mock_send_email.call_args
        assert "caddy failure" in args[0] or "AutoHeal Incident" in args[0]
        assert "Nginx/Caddy configuration syntax error" in args[1]
