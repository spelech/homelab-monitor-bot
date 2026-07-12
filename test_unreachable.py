import os
import sys
import uuid

# Set test environment variables before importing app modules
os.environ["DATABASE_URL"] = "sqlite:////containers/monitorbot/test_monitorbot.db"
os.environ["NTFY_URL"] = "https://ntfy.unreachable-test.wileyriley.com"
os.environ["WEBHOOK_BASE_URL"] = "https://monitorbot.wileyriley.com"
os.environ["WEBHOOK_TOKEN"] = "test_token_12345"
os.environ["TELEGRAM_BOT_TOKEN"] = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
os.environ["TELEGRAM_CHAT_ID"] = "987654321"

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

sys.path.append("/containers/monitorbot")

from app.database import init_db, SessionLocal, Target, Incident
from app.notifier import send_incident_notification, send_followup_notification

def main():
    print("Initializing test database...")
    init_db()

    db = SessionLocal()
    # Clean up old test records
    db.query(Incident).delete()
    db.query(Target).delete()
    db.commit()

    # Insert dummy target and incident
    target = Target(id="test-unreachable-container", type="docker")
    db.add(target)
    db.commit()

    incident_id = str(uuid.uuid4())
    incident = Incident(
        id=incident_id,
        target_id="test-unreachable-container",
        status="PENDING_USER",
        error_logs="Connection timeout connecting to database.",
        root_cause="Database container crashed due to OOM.",
        proposed_fix="docker restart db-container"
    )
    db.add(incident)
    db.commit()
    db.close()

    print(f"Created test incident {incident_id} for target 'test-unreachable-container'")
    print("Testing incident alert notification...")
    send_incident_notification(incident_id)

    print("\nTesting follow-up notification...")
    send_followup_notification(incident_id, "Database container restarted successfully and is healthy.", success=True)

    print("\nTest run complete.")

if __name__ == "__main__":
    main()
