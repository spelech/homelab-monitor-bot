import os
import sys
import pytest

# Ensure the app folder is in the system path so it can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set DATABASE_URL to a shared in-memory database so it persists across TestClient connections
os.environ["DATABASE_URL"] = "sqlite:///file:testdb?mode=memory&cache=shared&uri=true"

from app.database import Base, engine, SessionLocal, get_db, init_db
from app.main import app

@pytest.fixture(scope="function", autouse=True)
def init_test_db():
    init_db()
    yield
    SessionLocal.close_all()
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture(scope="function", autouse=True)
def override_get_db(db_session):
    def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.clear()

@pytest.fixture(scope="function", autouse=True)
def block_external_notifications(monkeypatch, request):
    """Globally block live NTFY and SMTP/Telegram notifications during test runs, except in dedicated notifier tests."""
    if "test_notifier" not in request.node.nodeid:
        monkeypatch.setattr("app.notifier.send_incident_notification", lambda *args, **kwargs: True)
        monkeypatch.setattr("app.notifier.send_followup_notification", lambda *args, **kwargs: True)
        monkeypatch.setattr("app.notifier.send_telegram_notification", lambda *args, **kwargs: True)
        monkeypatch.setattr("app.notifier.send_email_notification", lambda *args, **kwargs: True)
