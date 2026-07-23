import os
import logging
import base64
import requests
import html
import smtplib
from datetime import datetime

from email.message import EmailMessage
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

def send_email_notification(subject: str, body: str):
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    email_from = os.getenv("EMAIL_FROM", smtp_user)
    email_to = os.getenv("EMAIL_TO", "steven.pelech@gmail.com")

    if not smtp_server or not smtp_user or not smtp_pass:
        logger.warning("SMTP email skip: SMTP_SERVER, SMTP_USER, or SMTP_PASS not configured.")
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = email_from
        msg["To"] = email_to
        msg.set_content(body)

        with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        logger.info(f"Fallback email notification sent successfully to {email_to}.")
        return True
    except Exception as e:
        logger.error(f"Failed to send fallback email notification: {e}")
        return False


def send_telegram_notification(title: str, body: str, incident_id: str = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.info("Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    # Escape HTML to prevent parsing issues
    escaped_title = html.escape(title)
    escaped_body = html.escape(body)
    
    text = f"<b>{escaped_title}</b>\n\n{escaped_body}"
    
    payload = {
        "chat_id": int(chat_id),
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
    ntfy_user = os.getenv("NTFY_USER", "steve")
    ntfy_pass = os.getenv("NTFY_PASS")
    if ntfy_user and ntfy_pass:
        user_pass = f"{ntfy_user}:{ntfy_pass}"
        encoded = base64.b64encode(user_pass.encode("utf-8")).decode("utf-8")
        return f"Basic {encoded}"
    return None

def send_incident_notification(incident_id: str):
    ntfy_url = os.getenv("NTFY_URL", "https://ntfy.wileyriley.com").rstrip("/")
    ntfy_topic = os.getenv("NTFY_TOPIC", "alerts")
    webhook_base_url = os.getenv("WEBHOOK_BASE_URL", "https://monitorbot.wileyriley.com").rstrip("/")
    webhook_token = os.getenv("WEBHOOK_TOKEN")
    if not webhook_token:
        logger.error("WEBHOOK_TOKEN environment variable not set!")
        return

    db: Session = SessionLocal()
    try:
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            logger.error(f"Incident {incident_id} not found when trying to send notification.")
            return

        target_id = incident.target_id
        root_cause = incident.root_cause
        proposed_fix = incident.proposed_fix
        is_autopilot = (incident.status == "FIXING")

        if is_autopilot:
            title = f"🤖 AutoHeal Autopilot: Resolving {target_id}"
            message_body = (
                f"Container '{target_id}' has failed.\n\n"
                f"🔍 Root Cause:\n{root_cause}\n\n"
                f"🛠️ Proposed Fix:\n{proposed_fix}\n\n"
                f"⚡ Autopilot active: Executing fix immediately..."
            )
            actions_str = ""
        elif incident.status == "BLOCKED":
            title = f"🛑 AutoHeal BLOCKED: {target_id} Circuit Breaker"
            message_body = (
                f"Target '{target_id}' has repeatedly failed.\n\n"
                f"⚠️ Circuit breaker tripped due to excessive failures in the last 60 minutes.\n"
                f"Automatic recovery has been paused for this target. Please triage manually."
            )
            actions_str = ""
        else:
            title = f"🚨 AutoHeal Incident: {target_id} failure"
            message_body = (
                f"Container '{target_id}' has failed.\n\n"
                f"🔍 Root Cause:\n{root_cause}\n\n"
                f"🛠️ Proposed Fix:\n{proposed_fix}"
            )
            webhook_url = f"{webhook_base_url}/api/webhooks/{incident_id}?token={webhook_token}"
            # Construct Action Buttons Header
            # ntfy supports: http, Label, URL, method=POST, body=JSON
            actions_str = (
                f"http, Fix Now, {webhook_url}, method=POST, headers=Content-Type:application/json, body={{\\\"action\\\": \\\"fix\\\"}}; "
                f"http, Defer 24h, {webhook_url}, method=POST, headers=Content-Type:application/json, body={{\\\"action\\\": \\\"defer\\\"}}; "
                f"http, Ignore Target, {webhook_url}, method=POST, headers=Content-Type:application/json, body={{\\\"action\\\": \\\"ignore\\\"}}"
            )

        # Always try to send to Telegram as well if configured
        send_telegram_notification(title, message_body, incident_id)

        incident_priority = os.getenv("NOTIFICATION_PRIORITY", "max")
        headers = {
            "Title": safe_header(title),
            "Priority": incident_priority,
            "Tags": "robot,zap" if is_autopilot else ("no_entry" if incident.status == "BLOCKED" else "rotating_light,computer"),
        }
        if actions_str:
            headers["Actions"] = actions_str

        auth = get_auth_header()
        if auth:
            headers["Authorization"] = auth

        url = f"{ntfy_url}/{ntfy_topic}"
        logger.info(f"Sending notification for incident {incident_id} to {url}...")
        
        try:
            resp = requests.post(url, data=message_body.encode("utf-8"), headers=headers, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Notification sent successfully for incident {incident_id}")
                incident.last_notified_at = datetime.utcnow()
                db.commit()
                return
            else:
                logger.error(f"Failed to send notification to NTFY_URL. Status: {resp.status_code}, Body: {resp.text}")
        except Exception as conn_err:
            logger.warning(f"Failed to connect to NTFY_URL ({url}): {conn_err}. Directing fallback to SMTP email...")

        # Immediate Fallback: Email notification via SMTP when primary NTFY_URL is down/unreachable
        logger.info(f"Triggering immediate SMTP email fallback for incident {incident_id}...")
        
        # Build local LAN links and CLI commands for email body
        local_ip_webhook_base = os.getenv("LOCAL_WEBHOOK_BASE_URL", "http://10.0.0.10:9013").rstrip("/")
        email_body = message_body
        
        if incident.status == "PENDING_USER":
            fix_lan_url = f"{local_ip_webhook_base}/api/webhooks/{incident_id}?token={webhook_token}&action=fix"
            email_body += (
                f"\n\n--- 🌐 Outage Recovery Actions ---\n"
                f"If reverse proxy domains are down, click the local LAN link or run the CLI command below:\n\n"
                f"🔗 Direct LAN Fix Link: {fix_lan_url}\n\n"
                f"💻 Terminal CLI Command:\n"
                f"curl -X POST \"{local_ip_webhook_base}/api/webhooks/{incident_id}?token={webhook_token}\" "
                f"-H \"Content-Type: application/json\" -d '{{\"action\": \"fix\"}}'\n"
            )

        # Rate Limiting / Batching for Email Notifications:
        # If an email fallback was sent in the last 15 minutes, log and skip sending individual emails for cascading failures.
        global _last_email_sent_time
        if '_last_email_sent_time' not in globals():
            _last_email_sent_time = None
        
        now = datetime.utcnow()
        if _last_email_sent_time and (now - _last_email_sent_time).total_seconds() < 900:
            logger.info(f"Skipping individual email for incident {incident_id} (email rate limit active: max 1 digest per 15m).")
            return

        if send_email_notification(title, email_body):
            _last_email_sent_time = now
            logger.info(f"Fallback email notification sent for incident {incident_id}")




    except Exception as e:
        logger.error(f"Error sending notification: {e}")
    finally:
        db.close()



def send_followup_notification(incident_id: str, message: str, success: bool):
    ntfy_url = os.getenv("NTFY_URL", "https://ntfy.wileyriley.com").rstrip("/")
    ntfy_topic = os.getenv("NTFY_TOPIC", "alerts")

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

        followup_priority = os.getenv("FOLLOWUP_NOTIFICATION_PRIORITY", "high")
        headers = {
            "Title": safe_header(title),
            "Priority": followup_priority,
            "Tags": tags
        }

        auth = get_auth_header()
        if auth:
            headers["Authorization"] = auth

        url = f"{ntfy_url}/{ntfy_topic}"
        logger.info(f"Sending follow-up notification for {incident_id} to {url}...")
        
        try:
            resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Follow-up notification sent for incident {incident_id}")
                return
            else:
                logger.error(f"Failed to send follow-up to NTFY_URL. Status: {resp.status_code}, Body: {resp.text}")
        except Exception as conn_err:
            logger.warning(f"Failed to send follow-up to NTFY_URL ({url}): {conn_err}. Directing fallback to SMTP email...")

        # Immediate Fallback: Email notification via SMTP
        logger.info(f"Triggering immediate SMTP email fallback for follow-up on incident {incident_id}...")
        send_email_notification(title, message)

    except Exception as e:
        logger.error(f"Error sending follow-up notification: {e}")
    finally:
        db.close()


def send_heartbeat_notification():
    ntfy_url = os.getenv("NTFY_URL", "https://ntfy.wileyriley.com").rstrip("/")
    ntfy_topic = os.getenv("NTFY_TOPIC", "alerts")
    
    title = "💚 AutoHeal Heartbeat"
    message = "AutoHeal SRE MonitorBot is online, running health checks, and active."
    
    # Always try to send to Telegram as well if configured
    send_telegram_notification(title, message, None)

    headers = {
        "Title": safe_header(title),
        "Priority": "low",
        "Tags": "green_heart,nut_and_bolt"
    }

    auth = get_auth_header()
    if auth:
        headers["Authorization"] = auth

    url = f"{ntfy_url}/{ntfy_topic}"
    logger.info(f"Sending heartbeat notification to {url}...")
    
    try:
        resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
        if resp.status_code == 200:
            logger.info("Heartbeat notification sent successfully.")
            return
        else:
            logger.error(f"Failed to send heartbeat. Status: {resp.status_code}, Body: {resp.text}")
    except Exception as conn_err:
        logger.warning(f"Failed to send heartbeat to NTFY_URL ({url}): {conn_err}. Directing fallback to SMTP email...")

    # Immediate Fallback: Email notification via SMTP
    logger.info("Triggering immediate SMTP email fallback for heartbeat...")
    send_email_notification(title, message)


