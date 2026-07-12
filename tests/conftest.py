import os
import sys
import pytest

# Ensure the app folder is in the system path so it can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set DATABASE_URL to a shared in-memory database so it persists across TestClient connections
os.environ["DATABASE_URL"] = "sqlite:///file:testdb?mode=memory&cache=shared&uri=true"

from app.database import Base, engine, SessionLocal, get_db
from app.main import app

@pytest.fixture(scope="function", autouse=True)
def init_test_db():
    Base.metadata.create_all(bind=engine)
    yield
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
