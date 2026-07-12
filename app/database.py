import os
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, String, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////containers/monitorbot/monitorbot.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Target(Base):
    __tablename__ = "targets"

    id = Column(String, primary_key=True, index=True)  # container name
    type = Column(String, default="docker")
    ignored_until = Column(DateTime, nullable=True)

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, index=True)  # UUID
    target_id = Column(String, ForeignKey("targets.id"), nullable=False)
    status = Column(String, default="DETECTED")  # DETECTED, INVESTIGATING, PENDING_USER, FIXING, RESOLVED, FAILED, DEFERRED, IGNORED
    error_logs = Column(Text, nullable=True)
    root_cause = Column(Text, nullable=True)
    proposed_fix = Column(Text, nullable=True)
    execution_log = Column(Text, nullable=True)
    deferred_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
