import os
import re
import logging
import base64
import requests
import html
import smtplib
from datetime import datetime
from typing import Optional, List, Dict, Any

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

import ssl

def send_email_notification(subject: str, body: str, html_body: str = None):
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
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
        if html_body:
            msg.add_alternative(html_body, subtype="html")

        # Try SSL port 465 first or as configured
        if smtp_port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, 465, context=context, timeout=15) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            try:
                with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
            except Exception as starttls_err:
                logger.warning(f"STARTTLS on port {smtp_port} failed ({starttls_err}). Retrying via SSL port 465...")
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(smtp_server, 465, context=context, timeout=15) as server:
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
            # ntfy supports: http, Label, URL, method=POST, headers.<Header>=<Value>, body=JSON
            actions_str = (
                f"http, Fix Now, {webhook_url}, method=POST, headers.Content-Type=application/json, body={{\"action\":\"fix\"}}; "
                f"http, Defer 24h, {webhook_url}, method=POST, headers.Content-Type=application/json, body={{\"action\":\"defer\"}}; "
                f"http, Ignore Target, {webhook_url}, method=POST, headers.Content-Type=application/json, body={{\"action\":\"ignore\"}}"
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
            logger.warning(f"Failed to connect to NTFY_URL ({url}): {conn_err}.")

        # Direct LAN Fallback: Try local ntfy port directly if domain/proxy is down
        ntfy_fallback = os.getenv("NTFY_FALLBACK_URL", "http://localhost:9010").rstrip("/")
        fallback_url = f"{ntfy_fallback}/{ntfy_topic}"
        logger.info(f"Attempting direct local LAN ntfy fallback to {fallback_url}...")

        # Per AGENTS.md, action buttons in fallback request must point to local LAN IP
        local_ip_webhook_base = os.getenv("LOCAL_WEBHOOK_BASE_URL", "http://10.0.0.10:9013").rstrip("/")
        fallback_headers = dict(headers)
        if actions_str:
            fallback_webhook_url = f"{local_ip_webhook_base}/api/webhooks/{incident_id}?token={webhook_token}"
            fallback_headers["Actions"] = (
                f"http, Fix Now, {fallback_webhook_url}, method=POST, headers.Content-Type=application/json, body={{\"action\":\"fix\"}}; "
                f"http, Defer 24h, {fallback_webhook_url}, method=POST, headers.Content-Type=application/json, body={{\"action\":\"defer\"}}; "
                f"http, Ignore Target, {fallback_webhook_url}, method=POST, headers.Content-Type=application/json, body={{\"action\":\"ignore\"}}"
            )

        try:
            resp = requests.post(fallback_url, data=message_body.encode("utf-8"), headers=fallback_headers, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Notification sent successfully via local LAN ntfy ({fallback_url})")
                incident.last_notified_at = datetime.utcnow()
                db.commit()
                return
            else:
                logger.error(f"Local LAN ntfy fallback failed. Status: {resp.status_code}, Body: {resp.text}")
        except Exception as fb_err:
            logger.warning(f"Local LAN ntfy fallback error: {fb_err}")

        # Immediate Fallback: Email notification via SMTP when primary NTFY_URL is down/unreachable
        logger.info(f"Triggering immediate SMTP email fallback for incident {incident_id}...")
        
        # Build local LAN links and CLI commands for email body
        local_ip_webhook_base = os.getenv("LOCAL_WEBHOOK_BASE_URL", "http://10.0.0.10:9013").rstrip("/")
        email_body = message_body
        html_email_body = None
        
        if incident.status == "PENDING_USER":
            fix_public_url = f"{webhook_base_url}/api/webhooks/{incident_id}?token={webhook_token}&action=fix"
            defer_public_url = f"{webhook_base_url}/api/webhooks/{incident_id}?token={webhook_token}&action=defer"
            ignore_public_url = f"{webhook_base_url}/api/webhooks/{incident_id}?token={webhook_token}&action=ignore"

            fix_lan_url = f"{local_ip_webhook_base}/api/webhooks/{incident_id}?token={webhook_token}&action=fix"
            defer_lan_url = f"{local_ip_webhook_base}/api/webhooks/{incident_id}?token={webhook_token}&action=defer"
            ignore_lan_url = f"{local_ip_webhook_base}/api/webhooks/{incident_id}?token={webhook_token}&action=ignore"

            email_body += (
                f"\n\n--- 🌐 Outage Recovery Actions ---\n"
                f"🔗 Fix Action (Public): {fix_public_url}\n"
                f"🔗 Fix Action (Local LAN): {fix_lan_url}\n\n"
                f"💻 Terminal CLI Command:\n"
                f"curl -X POST \"{local_ip_webhook_base}/api/webhooks/{incident_id}?token={webhook_token}\" "
                f"-H \"Content-Type: application/json\" -d '{{\"action\": \"fix\"}}'\n"
            )

            html_email_body = f"""
<!DOCTYPE html>
<html>
<head>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 20px; }}
    .card {{ background-color: #1e293b; border-radius: 12px; padding: 24px; max-width: 600px; margin: 0 auto; border: 1px solid #334155; box-shadow: 0 10px 25px rgba(0,0,0,0.3); }}
    .title {{ color: #f43f5e; font-size: 20px; font-weight: 700; margin-bottom: 16px; border-bottom: 1px solid #334155; padding-bottom: 12px; }}
    .section {{ margin-bottom: 16px; font-size: 14px; line-height: 1.6; color: #cbd5e1; }}
    .highlight {{ background-color: #0f172a; padding: 12px; border-radius: 6px; font-family: monospace; font-size: 13px; color: #38bdf8; border-left: 4px solid #38bdf8; word-break: break-all; margin-top: 6px; }}
    .btn-group {{ margin-top: 24px; padding-top: 16px; border-top: 1px solid #334155; }}
    .btn {{ display: inline-block; padding: 12px 20px; border-radius: 8px; font-weight: 600; text-decoration: none; font-size: 14px; margin-right: 8px; margin-bottom: 8px; }}
    .btn-fix {{ background-color: #10b981; color: #ffffff; }}
    .btn-lan {{ background-color: #3b82f6; color: #ffffff; }}
    .btn-defer {{ background-color: #f59e0b; color: #ffffff; }}
    .btn-ignore {{ background-color: #64748b; color: #ffffff; }}
    .footer {{ font-size: 12px; color: #64748b; margin-top: 20px; text-align: center; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="title">🚨 AutoHeal SRE Incident Report</div>
    <div class="section"><strong>Failed Target:</strong> <code>{html.escape(str(target_id))}</code></div>
    <div class="section">
      <strong>🔍 Root Cause:</strong>
      <div class="highlight">{html.escape(str(root_cause))}</div>
    </div>
    <div class="section">
      <strong>🛠️ Proposed Fix:</strong>
      <div class="highlight">{html.escape(str(proposed_fix))}</div>
    </div>
    
    <div style="margin-top: 20px;">
      <strong style="color: #f8fafc; font-size: 15px;">⚡ Approve & Execute Action:</strong>
      <div class="btn-group">
        <a href="{fix_public_url}" class="btn btn-fix">🛠️ Approve Fix (Public)</a>
        <a href="{fix_lan_url}" class="btn btn-lan">🏠 Approve Fix (LAN)</a>
        <a href="{defer_lan_url}" class="btn btn-defer">⏳ Defer 24h</a>
        <a href="{ignore_lan_url}" class="btn btn-ignore">🚫 Ignore</a>
      </div>
    </div>
    <div class="footer">AutoHeal SRE MonitorBot • Local & Cloud Backup Controls</div>
  </div>
</body>
</html>
"""

        # Rate Limiting / Batching for Email Notifications:
        # If an email fallback was sent in the last 15 minutes, log and skip sending individual emails for cascading failures.
        global _last_email_sent_time
        if '_last_email_sent_time' not in globals():
            _last_email_sent_time = None
        
        now = datetime.utcnow()
        if _last_email_sent_time and (now - _last_email_sent_time).total_seconds() < 900:
            logger.info(f"Skipping individual email for incident {incident_id} (email rate limit active: max 1 digest per 15m).")
            return

        if send_email_notification(title, email_body, html_email_body):
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
            logger.warning(f"Failed to send follow-up to NTFY_URL ({url}): {conn_err}.")

        # Direct LAN Fallback: Try local ntfy port directly if domain/proxy is down
        ntfy_fallback = os.getenv("NTFY_FALLBACK_URL", "http://localhost:9010").rstrip("/")
        fallback_url = f"{ntfy_fallback}/{ntfy_topic}"
        logger.info(f"Attempting direct local LAN ntfy fallback to {fallback_url}...")
        try:
            resp = requests.post(fallback_url, data=message.encode("utf-8"), headers=headers, timeout=10)
            if resp.status_code == 200:
                logger.info(f"Follow-up notification sent via local LAN ntfy ({fallback_url})")
                return
            else:
                logger.error(f"Local LAN ntfy fallback failed for follow-up. Status: {resp.status_code}, Body: {resp.text}")
        except Exception as fb_err:
            logger.warning(f"Local LAN ntfy fallback error for follow-up: {fb_err}")

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
        logger.warning(f"Failed to send heartbeat to NTFY_URL ({url}): {conn_err}.")

    # Direct LAN Fallback: Try local ntfy port directly if domain/proxy is down
    ntfy_fallback = os.getenv("NTFY_FALLBACK_URL", "http://localhost:9010").rstrip("/")
    fallback_url = f"{ntfy_fallback}/{ntfy_topic}"
    logger.info(f"Attempting direct local LAN ntfy fallback to {fallback_url}...")
    try:
        resp = requests.post(fallback_url, data=message.encode("utf-8"), headers=headers, timeout=10)
        if resp.status_code == 200:
            logger.info(f"Heartbeat notification sent via local LAN ntfy ({fallback_url})")
            return
        else:
            logger.error(f"Local LAN ntfy fallback failed for heartbeat. Status: {resp.status_code}, Body: {resp.text}")
    except Exception as fb_err:
        logger.warning(f"Local LAN ntfy fallback error for heartbeat: {fb_err}")

    # Immediate Fallback: Email notification via SMTP
    logger.info("Triggering immediate SMTP email fallback for heartbeat...")
    send_email_notification(title, message)


def is_benign_warning(summary: str) -> bool:
    """
    Determines if an audit warning summary represents verified benign noise rather
    than an actionable issue requiring human attention.
    """
    if not summary:
        return True

    summary_lower = summary.lower()

    # Handle phrases indicating absence of actionable issues
    has_negated_actionable = "zero actionable" in summary_lower or "no actionable" in summary_lower

    # Positive indicators that attention is needed
    attention_keywords = [
        "requiring investigation",
        "requires attention",
        "needs investigation",
        "crash loop",
        "repeatedly failing",
        "connectivity failures",
        "active failures",
        "active outages",
        "schema migration failed",
        "dead 404",
        "connection refused",
        "bottleneck",
        "recording loss",
    ]
    if not has_negated_actionable and "actionable" in summary_lower:
        attention_keywords.append("actionable")

    if any(kw in summary_lower for kw in attention_keywords):
        return False

    # Indicators that the warnings are purely benign
    benign_keywords = [
        "is healthy",
        "are healthy",
        "fully operational",
        "operating normally",
        "benign",
        "expected benign noise",
        "known benign patterns",
        "no remediation needed",
        "no corrective action needed",
        "no containers require",
        "zero actionable",
        "no actionable",
        "non-fatal",
        "non-impacting",
        "cosmetic",
        "expected transient",
        "false positive",
    ]
    return any(kw in summary_lower for kw in benign_keywords)


def extract_concise_summary(text: str, max_chars: int = 100) -> str:
    """
    Extracts a concise, single-sentence summary suitable for push notification banners.
    Strips verbose introductory fluff.
    """
    if not text:
        return "Warning detected"

    cleaned = text.strip()
    # Strip opening generic status phrases like "The monitoring stack is mostly healthy with two actionable items:"
    cleaned = re.sub(
        r"^(?:(?:The\s+)?['\"]?[\w\-]+['\"]?\s+stack\s+is\s+(?:mostly\s+)?healthy[.,;:]*\s*|Stack\s+(?:['\"]?[\w\-]+['\"]?\s+)?is\s+healthy[.,;:]*\s*)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:with\s+)?(?:two|one|\d+)?\s*(?:independent\s+|actionable\s+)?(?:items|issues)?:?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:All\s+\d+\s+containers\s+in\s+[\w\-]+\s+stack\s+are\s+running\s+healthy[.,;:]*\s*)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^Only\s+", "", cleaned, flags=re.IGNORECASE)

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
    target_sentence = sentences[0] if sentences else cleaned

    if len(target_sentence) > max_chars:
        target_sentence = target_sentence[:max_chars].rsplit(" ", 1)[0] + "..."
    return target_sentence


def send_sre_digest_notification(results: list, preview_url: Optional[str] = None) -> bool:
    """
    Sends a consolidated daily SRE audit digest notification across all stacks.
    Filters benign log noise so the user only sees actionable/notable issues,
    enforces strict character limits to prevent push notification cutoff,
    and attaches action buttons linking directly to the full report and dashboard.
    """
    total_stacks = len(results)
    active_outages = [r for r in results if r.get("status") == "ACTION_REQUIRED"]
    active_outages_count = len(active_outages)
    all_warnings = [r for r in results if r.get("status") == "WARNING"]
    warnings_count = len(all_warnings)

    attention_needed = []
    clean_or_benign = []

    for r in results:
        status = r.get("status")
        if status == "ACTION_REQUIRED":
            continue
        summary = r.get("summary") or r.get("root_cause") or ""
        if status == "WARNING" and not is_benign_warning(summary):
            attention_needed.append(r)
        else:
            clean_or_benign.append(r)

    clean_count = len(clean_or_benign)

    if active_outages_count > 0:
        title = f"🚨 Daily SRE Audit: {active_outages_count} Outage(s)"
        priority = "high"
        tag = "warning,rotating_light"
    elif len(attention_needed) > 0:
        title = f"⚠️ Daily SRE Audit: {len(attention_needed)} Attention Item(s)"
        priority = "default"
        tag = "warning,clipboard"
    else:
        title = f"✅ Daily SRE Audit: All {total_stacks} Stacks Clean"
        priority = "low"
        tag = "white_check_mark,clipboard"

    # Base opening line preserves backward compatibility with test assertions
    message_body = (
        f"📊 Daily SRE Audit: {total_stacks} stacks checked. "
        f"{active_outages_count} active outages. {warnings_count} warnings logged."
    )

    if active_outages:
        message_body += f"\n\n🚨 Active Outages ({len(active_outages)}):"
        for outage in active_outages:
            st_name = outage.get("stack_name", "unknown")
            root = extract_concise_summary(outage.get("root_cause") or outage.get("summary") or "Action required")
            message_body += f"\n• {st_name}: {root}"

    if attention_needed:
        message_body += f"\n\n⚠️ Needs Attention ({len(attention_needed)}):"
        for att in attention_needed[:8]:
            st_name = att.get("stack_name", "unknown")
            sum_txt = extract_concise_summary(att.get("summary") or att.get("root_cause") or "Attention required")
            message_body += f"\n• {st_name}: {sum_txt}"
        if len(attention_needed) > 8:
            message_body += f"\n... and {len(attention_needed) - 8} more."

    benign_filtered = warnings_count - len(attention_needed)
    if benign_filtered > 0:
        message_body += f"\n\n✅ {clean_count} stacks clean ({benign_filtered} benign noise filtered)"
    else:
        message_body += f"\n\n✅ {clean_count} stacks clean & healthy"

    report_url = preview_url or os.getenv("SRE_REPORT_URL", "https://preview.wileyriley.com/sre-audit-daily/")
    dashboard_url = os.getenv("WEBHOOK_BASE_URL", "https://monitorbot.wileyriley.com").rstrip("/")
    message_body += f"\n\n📄 Full Report: {report_url}"

    # Enforce strict length cap to prevent NTFY mobile push truncation
    if len(message_body) > 1200:
        message_body = message_body[:1150].rsplit("\n", 1)[0] + f"\n... [Report truncated: see {report_url}]"

    # Always try to send to Telegram as well if configured
    send_telegram_notification(title, message_body, None)

    # NTFY Action buttons
    actions_str = f"view, Full Report, {report_url}; view, Dashboard, {dashboard_url}"

    headers = {
        "Title": safe_header(title),
        "Priority": priority,
        "Tags": "clipboard",
        "Actions": actions_str,
    }

    auth = get_auth_header()
    if auth:
        headers["Authorization"] = auth

    ntfy_url = os.getenv("NTFY_URL", "https://ntfy.wileyriley.com").rstrip("/")
    ntfy_topic = os.getenv("NTFY_TOPIC", "alerts")
    url = f"{ntfy_url}/{ntfy_topic}"
    logger.info(f"Sending SRE daily digest notification to {url}...")

    try:
        resp = requests.post(url, data=message_body.encode("utf-8"), headers=headers, timeout=10)
        if resp.status_code == 200:
            logger.info("SRE daily digest notification sent successfully.")
            return True
        else:
            logger.error(f"Failed to send SRE digest to NTFY_URL. Status: {resp.status_code}, Body: {resp.text}")
    except Exception as conn_err:
        logger.warning(f"Failed to send SRE digest to NTFY_URL ({url}): {conn_err}.")

    # Direct LAN Fallback: Try local ntfy port directly if domain/proxy is down
    ntfy_fallback = os.getenv("NTFY_FALLBACK_URL", "http://localhost:9010").rstrip("/")
    fallback_url = f"{ntfy_fallback}/{ntfy_topic}"
    logger.info(f"Attempting direct local LAN ntfy fallback for SRE digest to {fallback_url}...")

    local_dashboard = os.getenv("LOCAL_WEBHOOK_BASE_URL", "http://10.0.0.10:9013").rstrip("/")
    local_report = "http://preview.lan/sre-audit-daily/"
    fallback_headers = dict(headers)
    fallback_headers["Actions"] = f"view, Full Report, {local_report}; view, Dashboard, {local_dashboard}"

    try:
        resp = requests.post(fallback_url, data=message_body.encode("utf-8"), headers=fallback_headers, timeout=10)
        if resp.status_code == 200:
            logger.info(f"SRE daily digest notification sent via local LAN ntfy ({fallback_url})")
            return True
        else:
            logger.error(f"Local LAN ntfy fallback failed for SRE digest. Status: {resp.status_code}, Body: {resp.text}")
    except Exception as fb_err:
        logger.warning(f"Local LAN ntfy fallback error for SRE digest: {fb_err}")

    # Immediate Fallback: Email notification via SMTP
    logger.info("Triggering immediate SMTP email fallback for SRE daily digest...")
    return bool(send_email_notification(title, message_body))



