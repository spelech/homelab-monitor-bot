import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from app.scheduler import check_deferred_and_ignored
from app.database import Incident, Target

def test_check_deferred_and_ignored_expired_incidents(db_session):
    target = Target(id="stale_target", type="docker")
    db_session.add(target)
    
    # Stale PENDING_USER incident older than 24h
    stale_dt = datetime.utcnow() - timedelta(hours=25)
    inc = Incident(id="inc-stale-1", target_id="stale_target", status="PENDING_USER", created_at=stale_dt)
    db_session.add(inc)
    db_session.commit()
    
    with patch("app.database.check_maintenance_status", return_value=(False, "")):
        check_deferred_and_ignored()
        db_session.refresh(inc)
        assert inc.status == "EXPIRED"
