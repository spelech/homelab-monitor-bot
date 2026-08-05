import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, String, DateTime, Text, ForeignKey, Enum, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./monitorbot.db")

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
    category = Column(String, nullable=True)  # network, reverse_proxy, permissions, settings, database, unknown
    completed_at = Column(DateTime, nullable=True)
    last_notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class SystemSetting(Base):
    __tablename__ = "system_settings"

    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)

def init_db():
    Base.metadata.create_all(bind=engine)
    # Perform a lightweight schema migration to add new columns if they do not exist
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('incidents')]
    with engine.begin() as conn:
        if 'category' not in columns:
            conn.execute(text("ALTER TABLE incidents ADD COLUMN category VARCHAR;"))
        if 'completed_at' not in columns:
            conn.execute(text("ALTER TABLE incidents ADD COLUMN completed_at DATETIME;"))
        if 'last_notified_at' not in columns:
            conn.execute(text("ALTER TABLE incidents ADD COLUMN last_notified_at DATETIME;"))

    # Seed default system settings
    db = SessionLocal()
    try:
        if not db.query(SystemSetting).filter(SystemSetting.key == "silent_mode").first():
            db.add(SystemSetting(key="silent_mode", value="false"))
        if not db.query(SystemSetting).filter(SystemSetting.key == "autopilot").first():
            db.add(SystemSetting(key="autopilot", value="false"))
        if not db.query(SystemSetting).filter(SystemSetting.key == "maintenance_mode").first():
            db.add(SystemSetting(key="maintenance_mode", value="false"))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

def get_setting(key: str, default: str = "false") -> str:
    db = SessionLocal()
    try:
        setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if setting:
            return setting.value
        return default
    except Exception:
        return default
    finally:
        db.close()

def set_setting(key: str, value: str):
    db = SessionLocal()
    try:
        setting = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if not setting:
            setting = SystemSetting(key=key, value=value)
            db.add(setting)
        else:
            setting.value = value
        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_maintenance_status(db=None) -> tuple[bool, str]:
    if db is not None:
        try:
            setting = db.query(SystemSetting).filter(SystemSetting.key == "maintenance_mode").first()
            val = setting.value if setting else "false"
        except Exception:
            val = get_setting("maintenance_mode", "false")
    else:
        val = get_setting("maintenance_mode", "false")

    if val == "indefinite":
        return True, "Manual maintenance (indefinite)"
    elif val != "false":
        try:
            val_clean = val.replace("Z", "+00:00")
            expire_dt = datetime.fromisoformat(val_clean)
            if expire_dt.tzinfo is not None:
                expire_dt = expire_dt.astimezone(timezone.utc).replace(tzinfo=None)
            now_utc = datetime.utcnow()
            if expire_dt > now_utc:
                time_left = expire_dt - now_utc
                mins = int(time_left.total_seconds() // 60)
                secs = int(time_left.total_seconds() % 60)
                return True, f"Manual maintenance ({mins}m {secs}s remaining)"
        except Exception:
            pass

    # 2. Check auto-maintenance via active host processes
    try:
        my_pid = os.getpid()
        pid_to_ppid = {}
        processes = []

        if os.path.exists('/proc'):
            for pid_dir in os.listdir('/proc'):
                if pid_dir.isdigit():
                    try:
                        pid = int(pid_dir)
                        ppid = 0
                        with open(f'/proc/{pid_dir}/status', 'r', errors='ignore') as sf:
                            for line in sf:
                                if line.startswith('PPid:'):
                                    ppid = int(line.split()[1])
                                    break
                        pid_to_ppid[pid] = ppid

                        with open(f'/proc/{pid_dir}/cmdline', 'r', errors='ignore') as f:
                            cmdline = f.read().replace('\x00', ' ').strip()
                        if cmdline:
                            processes.append((pid, cmdline))
                    except Exception:
                        pass

        def is_descendant_of_monitorbot(pid: int) -> bool:
            curr = pid
            visited = set()
            while curr in pid_to_ppid and curr not in visited:
                ppid = pid_to_ppid[curr]
                if ppid == my_pid:
                    return True
                curr = ppid
                visited.add(curr)
            return False

        for pid, cmd in processes:
            cmd_lower = cmd.lower()

            # Check for update/lifecycle scripts
            for script in ["update_all.sh", "updown.sh", "down.sh"]:
                if script in cmd_lower:
                    return True, f"Active update script: '{cmd}'"

            # Check for modifying docker compose commands
            if "docker compose" in cmd_lower or "docker-compose" in cmd_lower:
                modifying_kws = ["up", "down", "stop", "restart", "pull", "build", "rm", "create"]
                tokens = cmd_lower.split()
                if any(kw in tokens for kw in modifying_kws):
                    return True, f"Active docker compose: '{cmd}'"

            # Check for external coding agents
            if "agy" in cmd_lower or "antigravity-cli" in cmd_lower:
                if not is_descendant_of_monitorbot(pid) and pid != my_pid:
                    return True, f"Active AI coding agent (PID {pid}): '{cmd}'"
    except Exception as proc_err:
        # Fallback gracefully if process inspection fails
        pass

    return False, ""

