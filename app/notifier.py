import os
import logging
import base64
import requests
from email.header import Header
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from app.database import SessionLocal, Incident

load_dotenv()

def safe_header(value: str) -> str:
    try:
        value.encode('ascii')
        return value
    except UnicodeEncodeError:
        return Header(value, 'utf-8').encode()

logger = logging.getLogger("Notifier")

NTFY_URL = os.getenv("NTFY_URL", "https://ntfy.wileyriley.com").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "alerts")
NTFY_USER = os.getenv("NTFY_USER", "steve")
NTFY_PASS = os.getenv("NTFY_PASS", "topfire89")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://monitorbot.wileyriley.com").rstrip("/")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "topfire89_monitorbot_secret_token")

def get_auth_header():
    if NTFY_USER and NTFY_PASS:
        user_pass = f"{NTFY_USER}:{NTFY_PASS}"
        encoded = base64.b64encode(user_pass.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"
    return None

def send_incident_notification(incident_id: str):
    db: Session = SessionLocal()
    try:
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            logger.error(f"Incident {incident_id} not found when trying to send notification.")
            return

        target_id = incident.target_id
        root_cause = incident.root_cause
        proposed_fix = incident.proposed_fix

        title = f"🚨 AutoHeal Incident: {target_id} failure"
        message_body = (
            f"Container '{target_id}' has failed.\n\n"
            f"🔍 Root Cause:\n{root_cause}\n\n"
            f"🛠️ Proposed Fix:\n{proposed_fix}"
        )

        webhook_url = f"{WEBHOOK_BASE_URL}/api/webhooks/{incident_id}?token={WEBHOOK_TOKEN}"

        # Construct Action Buttons Header
        # ntfy supports: http, Label, URL, method=POST, body=JSON
        actions_str = (
            f"http, Fix Now, {webhook_url}, method=POST, body={{\\\"action\\\": \\\"fix\\\"}}; "
            f"http, Defer 24h, {webhook_url}, method=POST, body={{\\\"action\\\": \\\"defer\\\"}}; "
            f"http, Ignore 24h, {webhook_url}, method=POST, body={{\\\"action\\\": \\\"ignore\\\"}}"
        )

        headers = {
            "Title": safe_header(title),
            "Priority": "high",
            "Tags": "rotating_light,robot",
            "Actions": actions_str
        }

        auth = get_auth_header()
        if auth:
            headers["Authorization"] = auth

        url = f"{NTFY_URL}/{NTFY_TOPIC}"
        logger.info(f"Sending notification for incident {incident_id} to {url}...")
        resp = requests.post(url, data=message_body.encode("utf-8"), headers=headers, timeout=10)

        if resp.status_code == 200:
            logger.info(f"Notification sent successfully for incident {incident_id}")
        else:
            logger.error(f"Failed to send notification. Status: {resp.status_code}, Body: {resp.text}")

    except Exception as e:
        logger.error(f"Error sending ntfy notification: {e}")
    finally:
        db.close()

def send_followup_notification(incident_id: str, message: str, success: bool):
    db: Session = SessionLocal()
    try:
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            logger.error(f"Incident {incident_id} not found for follow-up.")
            return

        target_id = incident.target_id
        title = f"{'✅' if success else '❌'} AutoHeal Update: {target_id}"
        tags = "white_check_mark" if success else "x"

        headers = {
            "Title": safe_header(title),
            "Priority": "default",
            "Tags": tags
        }

        auth = get_auth_header()
        if auth:
            headers["Authorization"] = auth

        url = f"{NTFY_URL}/{NTFY_TOPIC}"
        logger.info(f"Sending follow-up notification for {incident_id} to {url}...")
        resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)

        if resp.status_code == 200:
            logger.info(f"Follow-up notification sent for incident {incident_id}")
        else:
            logger.error(f"Failed to send follow-up. Status: {resp.status_code}, Body: {resp.text}")

    except Exception as e:
        logger.error(f"Error sending follow-up notification: {e}")
    finally:
        db.close()
