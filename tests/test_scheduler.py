"""
tests/test_scheduler.py
~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for background scheduler jobs and re-notification triggers.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app.database import Incident, Target
from app.scheduler import check_deferred_and_ignored

def test_expired_ignores_cleared(db_session):
    # Setup an ignored target whose ignore period has expired
    expired_time = datetime.utcnow() - timedelta(minutes=5)
    target = Target(id="test-expired-target", type="docker", ignored_until=expired_time)
    db_session.add(target)
    db_session.commit()

    check_deferred_and_ignored()

    db_session.expire_all()
    target_db = db_session.query(Target).filter_by(id="test-expired-target").first()
    assert target_db.ignored_until is None

def test_future_ignores_preserved(db_session):
    # Setup an ignored target whose ignore period is in the future
    future_time = datetime.utcnow() + timedelta(hours=2)
    target = Target(id="test-future-target", type="docker", ignored_until=future_time)
    db_session.add(target)
    db_session.commit()

    check_deferred_and_ignored()

    db_session.expire_all()
    target_db = db_session.query(Target).filter_by(id="test-future-target").first()
    assert target_db.ignored_until == future_time

def test_deferred_incidents_retried(db_session):
    target = Target(id="test-deferred-target", type="docker")
    db_session.add(target)
    db_session.commit()

    # Setup a deferred incident whose deferral period has expired
    expired_time = datetime.utcnow() - timedelta(minutes=5)
    incident = Incident(
        id="inc-def-001",
        target_id="test-deferred-target",
        status="DEFERRED",
        deferred_until=expired_time
    )
    db_session.add(incident)
    db_session.commit()

    with patch("app.scheduler.send_incident_notification") as mock_notify:
        check_deferred_and_ignored()
        mock_notify.assert_called_once_with("inc-def-001")

    db_session.expire_all()
    inc_db = db_session.query(Incident).filter_by(id="inc-def-001").first()
    assert inc_db.status == "PENDING_USER"
    assert inc_db.deferred_until is None

def test_renotify_unresponded_incidents(db_session):
    target = Target(id="test-renotify-target", type="docker")
    db_session.add(target)
    db_session.commit()

    # 1. Setup a PENDING_USER incident created 2 hours ago with last_notified_at 2 hours ago
    two_hours_ago = datetime.utcnow() - timedelta(hours=2)
    incident = Incident(
        id="inc-renotify-001",
        target_id="test-renotify-target",
        status="PENDING_USER",
        created_at=two_hours_ago,
        last_notified_at=two_hours_ago
    )
    db_session.add(incident)
    db_session.commit()

    # 2. Setup a PENDING_USER incident created 10 minutes ago (should NOT trigger)
    ten_mins_ago = datetime.utcnow() - timedelta(minutes=10)
    incident_recent = Incident(
        id="inc-norenotify-002",
        target_id="test-renotify-target",
        status="PENDING_USER",
        created_at=ten_mins_ago,
        last_notified_at=ten_mins_ago
    )
    db_session.add(incident_recent)
    db_session.commit()

    with patch("app.scheduler.send_incident_notification") as mock_notify:
        check_deferred_and_ignored()
        # Should only trigger for the old one
        mock_notify.assert_called_once_with("inc-renotify-001")

def test_renotify_handles_null_last_notified_at(db_session):
    target = Target(id="test-renotify-null", type="docker")
    db_session.add(target)
    db_session.commit()

    # Setup an incident created 2 hours ago where last_notified_at is Null (e.g. from older schema)
    two_hours_ago = datetime.utcnow() - timedelta(hours=2)
    incident = Incident(
        id="inc-renotify-003",
        target_id="test-renotify-null",
        status="PENDING_USER",
        created_at=two_hours_ago,
        last_notified_at=None
    )
    db_session.add(incident)
    db_session.commit()

    with patch("app.scheduler.send_incident_notification") as mock_notify:
        check_deferred_and_ignored()
        mock_notify.assert_called_once_with("inc-renotify-003")
