import os
import logging
import base64
import requests
import html
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
        return Header(value, 'utf-8', maxlinelen=999999).encode()

logger = logging.getLogger("Notifier")

NTFY_URL = os.getenv("NTFY_URL", "https://ntfy.wileyriley.com").rstrip("/")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "alerts")
NTFY_USER = os.getenv("NTFY_USER", "steve")
NTFY_PASS = os.getenv("NTFY_PASS")
WEBHOOK_BASE_URL = os.getenv("WEBHOOK_BASE_URL", "https://monitorbot.wileyriley.com").rstrip("/")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN")
if not WEBHOOK_TOKEN:
    raise ValueError("WEBHOOK_TOKEN environment variable must be set!")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_notification(title: str, body: str, incident_id: str = None):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.info("Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Escape HTML to prevent parsing issues
    escaped_title = html.escape(title)
    escaped_body = html.escape(body)
    
    text = f"<b>{escaped_title}</b>\n\n{escaped_body}"
    
    payload = {
        "chat_id": int(TELEGRAM_CHAT_ID),
        "text": text,
        "parse_mode": "HTML"
    }
    
    if incident_id:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [
                    {"text": "🛠️ Fix Now", "callback_data": f"fix:{incident_id}"},
                    {"text": "⏳ Defer 24h", "callback_data": f"defer:{incident_id}"},
                    {"text": "🚫 Ignore 24h", "callback_data": f"ignore:{incident_id}"}
                ]
            ]
        }
        
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Telegram notification sent successfully.")
        else:
            logger.error(f"Failed to send Telegram notification. Status: {resp.status_code}, Body: {resp.text}")
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")

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

        # Always try to send to Telegram as well if configured
        send_telegram_notification(title, message_body, incident_id)

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
        
        try:
            resp = requests.post(url, data=message_body.encode("utf-8"), headers=headers, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Notification sent successfully for incident {incident_id}")
                return
            else:
                logger.error(f"Failed to send notification. Status: {resp.status_code}, Body: {resp.text}")
                # Fall through to fallback
        except Exception as conn_err:
            logger.warning(f"Failed to connect to primary NTFY_URL ({url}): {conn_err}. Trying local fallback...")

        # Fallback to local URL and local action webhook
        local_ntfy_url = f"http://localhost:9010/{NTFY_TOPIC}"
        local_webhook_url = f"http://10.0.0.10:9013/api/webhooks/{incident_id}?token={WEBHOOK_TOKEN}"
        
        local_actions_str = (
            f"http, Fix Now (Local), {local_webhook_url}, method=POST, body={{\\\"action\\\": \\\"fix\\\"}}; "
            f"http, Defer 24h (Local), {local_webhook_url}, method=POST, body={{\\\"action\\\": \\\"defer\\\"}}; "
            f"http, Ignore 24h (Local), {local_webhook_url}, method=POST, body={{\\\"action\\\": \\\"ignore\\\"}}"
        )
        
        fallback_headers = {
            "Title": safe_header(f"{title} (Local Fallback)"),
            "Priority": "high",
            "Tags": "rotating_light,robot",
            "Actions": local_actions_str
        }
        if auth:
            fallback_headers["Authorization"] = auth
            
        logger.info(f"Sending fallback notification for incident {incident_id} to {local_ntfy_url}...")
        fallback_resp = requests.post(local_ntfy_url, data=message_body.encode("utf-8"), headers=fallback_headers, timeout=10)
        if fallback_resp.status_code == 200:
            logger.info(f"Fallback notification sent successfully for incident {incident_id}")
        else:
            logger.error(f"Failed to send fallback notification. Status: {fallback_resp.status_code}, Body: {fallback_resp.text}")

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

        # Always try to send to Telegram as well if configured
        send_telegram_notification(title, message, None)

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
        
        try:
            resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Follow-up notification sent for incident {incident_id}")
                return
            else:
                logger.error(f"Failed to send follow-up. Status: {resp.status_code}, Body: {resp.text}")
                # Fall through to fallback
        except Exception as conn_err:
            logger.warning(f"Failed to send follow-up to primary NTFY_URL ({url}): {conn_err}. Trying local fallback...")

        # Fallback to local URL
        local_ntfy_url = f"http://localhost:9010/{NTFY_TOPIC}"
        fallback_headers = {
            "Title": safe_header(f"{title} (Local Fallback)"),
            "Priority": "default",
            "Tags": tags
        }
        if auth:
            fallback_headers["Authorization"] = auth

        logger.info(f"Sending fallback follow-up notification to {local_ntfy_url}...")
        fallback_resp = requests.post(local_ntfy_url, data=message.encode("utf-8"), headers=fallback_headers, timeout=10)
        if fallback_resp.status_code == 200:
            logger.info(f"Fallback follow-up notification sent for incident {incident_id}")
        else:
            logger.error(f"Failed to send fallback follow-up. Status: {fallback_resp.status_code}, Body: {fallback_resp.text}")

    except Exception as e:
        logger.error(f"Error sending follow-up notification: {e}")
    finally:
        db.close()
