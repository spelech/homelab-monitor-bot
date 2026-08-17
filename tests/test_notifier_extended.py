import pytest
from unittest.mock import patch, MagicMock
from app.notifier import (
    send_incident_notification,
    send_followup_notification,
    send_email_notification,
    get_auth_header
)
from app.database import Incident, Target

def test_get_auth_header(monkeypatch):
    monkeypatch.setenv("NTFY_USER", "admin")
    monkeypatch.setenv("NTFY_PASS", "pass123")
    header = get_auth_header()
    assert header.startswith("Basic ")

@patch("requests.post")
def test_send_incident_notification_flow(mock_post, db_session):
    target = Target(id="notify_target", type="docker")
    inc = Incident(
        id="inc-notify-1",
        target_id="notify_target",
        status="PENDING_USER",
        root_cause="Bad config",
        proposed_fix="docker restart notify_target",
        category="settings"
    )
    db_session.add_all([target, inc])
    db_session.commit()
    
    mock_post.return_value = MagicMock(status_code=200)
    
    send_incident_notification("inc-notify-1")
    assert mock_post.called

@patch("requests.post")
def test_send_incident_notification_blocked_and_autopilot(mock_post, db_session):
    target = Target(id="blocked_target", type="docker")
    inc_blocked = Incident(
        id="inc-blocked-1",
        target_id="blocked_target",
        status="BLOCKED",
        root_cause="Crash loop",
        proposed_fix="manual intervention",
        category="crash"
    )
    inc_auto = Incident(
        id="inc-auto-1",
        target_id="blocked_target",
        status="FIXING",
        root_cause="Temp lock",
        proposed_fix="docker restart blocked_target",
        category="lock"
    )
    db_session.add_all([target, inc_blocked, inc_auto])
    db_session.commit()
    
    mock_post.return_value = MagicMock(status_code=200)
    
    send_incident_notification("inc-blocked-1")
    send_incident_notification("inc-auto-1")
    assert mock_post.call_count >= 2

@patch("requests.post")
def test_send_followup_notification_flow(mock_post, db_session):
    target = Target(id="followup_target", type="docker")
    inc = Incident(id="inc-follow-1", target_id="followup_target", status="RESOLVED")
    db_session.add_all([target, inc])
    db_session.commit()
    
    mock_post.return_value = MagicMock(status_code=200)
    
    send_followup_notification("inc-follow-1", "Resolution verified healthy", success=True)
    assert mock_post.called

@patch("smtplib.SMTP_SSL")
def test_send_email_notification(mock_smtp, monkeypatch):
    monkeypatch.setenv("SMTP_SERVER", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "test@example.com")
    monkeypatch.setenv("SMTP_PASS", "secret")
    
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server
    
    res = send_email_notification("Test Subject", "Test Body")
    assert res is True
    mock_server.send_message.assert_called_once()
