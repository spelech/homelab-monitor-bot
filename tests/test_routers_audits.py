import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, Incident, StackAudit, Target
from app.main import app

# Setup test in-memory SQLite database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_get_daily_audits_returns_30_day_structure(client, db_session):
    now = datetime.utcnow()
    # Create sample stack audits for today and yesterday
    today_audit_1 = StackAudit(
        id="audit-today-1",
        stack_name="media_content",
        status="WARNING",
        summary="Radarr4k JSON error",
        error_count="5",
        containers_checked="6",
        created_at=now,
    )
    today_audit_2 = StackAudit(
        id="audit-today-2",
        stack_name="smarthome",
        status="HEALTHY",
        summary="Stack is healthy",
        error_count="0",
        containers_checked="4",
        created_at=now,
    )
    yesterday_audit = StackAudit(
        id="audit-yesterday-1",
        stack_name="monitoring",
        status="ACTION_REQUIRED",
        summary="Autokuma down",
        error_count="10",
        containers_checked="8",
        created_at=now - timedelta(days=1),
    )
    db_session.add_all([today_audit_1, today_audit_2, yesterday_audit])

    # Add an actionable incident linked to today's audit
    target = Target(id="radarr4k", type="docker")
    incident = Incident(
        id="inc-today-1",
        target_id="radarr4k",
        status="PENDING_USER",
        stack_name="media_content",
        origin="sre_daily_audit",
        root_cause="Invalid boolean value in Apprise settings",
        proposed_fix="UPDATE Notifications SET Settings = REPLACE(Settings, '\"includePoster\":0', '\"includePoster\":false');",
        created_at=now,
    )
    db_session.add_all([target, incident])
    db_session.commit()

    resp = client.get("/api/audits/daily?days=30")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 2

    # Verify today's audit structure
    today_str = now.strftime("%Y-%m-%d")
    today_report = next((r for r in data if r["date"] == today_str), None)
    assert today_report is not None
    assert today_report["total_stacks"] == 2
    assert today_report["warning_count"] == 1
    assert today_report["healthy_count"] == 1
    assert len(today_report["actionable_items"]) == 1
    item = today_report["actionable_items"][0]
    assert item["incident_id"] == "inc-today-1"
    assert item["target_id"] == "radarr4k"
    assert item["can_action"] is True
    assert "UPDATE Notifications" in item["proposed_fix"]


def test_bulk_incident_actions(client, db_session):
    now = datetime.utcnow()
    t1 = Target(id="target-1", type="docker")
    t2 = Target(id="target-2", type="docker")
    inc1 = Incident(
        id="inc-bulk-1",
        target_id="target-1",
        status="PENDING_USER",
        created_at=now,
    )
    inc2 = Incident(
        id="inc-bulk-2",
        target_id="target-2",
        status="PENDING_USER",
        created_at=now,
    )
    db_session.add_all([t1, t2, inc1, inc2])
    db_session.commit()

    # Bulk dismiss
    payload = {
        "action": "dismiss",
        "incident_ids": ["inc-bulk-1", "inc-bulk-2"],
    }
    resp = client.post("/api/audits/actions/bulk", json=payload)
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "ok"
    assert res_data["processed"] == 2

    # Verify both incidents are resolved
    updated_1 = db_session.query(Incident).filter(Incident.id == "inc-bulk-1").first()
    updated_2 = db_session.query(Incident).filter(Incident.id == "inc-bulk-2").first()
    assert updated_1.status == "RESOLVED"
    assert updated_2.status == "RESOLVED"
