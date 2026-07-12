import os
import sys
import pytest

# Ensure the app folder is in the system path so it can be imported
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Set DATABASE_URL to a temporary in-memory database to avoid touching the actual database
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.database import Base, engine, SessionLocal

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
