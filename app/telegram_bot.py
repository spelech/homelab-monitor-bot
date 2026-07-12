import os
import time
import logging
import requests
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv

from app.database import SessionLocal, Incident, Target
from app.remediator import run_remediation

load_dotenv()

logger = logging.getLogger("TelegramBot")

def start_telegram_listener():
    t = threading.Thread(target=poll_telegram_updates, daemon=True)
    t.start()
    logger.info("Telegram updates listener thread spawned.")

def poll_telegram_updates():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id_env = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id_env:
        logger.info("Telegram bot configuration is incomplete (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing). Polling listener disabled.")
        return

    try:
        allowed_chat_id = int(chat_id_env)
    except ValueError:
        logger.error("TELEGRAM_CHAT_ID must be an integer.")
        return

    offset = 0
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    logger.info("Telegram listener polling started...")

    while True:
        try:
            params = {"offset": offset, "timeout": 30}
            resp = requests.get(url, params=params, timeout=35)
            if resp.status_code != 200:
                logger.error(f"Telegram getUpdates returned status code {resp.status_code}")
                time.sleep(5)
                continue

            updates = resp.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1

                # Check for callback query (interactive buttons)
                callback_query = update.get("callback_query")
                if callback_query:
                    # Validate sender chat ID
                    from_user = callback_query.get("from", {})
                    user_id = from_user.get("id")
                    
                    message = callback_query.get("message", {})
                    chat = message.get("chat", {})
                    chat_id = chat.get("id", user_id)

                    if chat_id != allowed_chat_id:
                        logger.warning(f"Unauthorized Telegram callback query from chat_id {chat_id} (Expected: {allowed_chat_id})")
                        # Acknowledge callback to prevent user UI hang
                        requests.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            json={"callback_query_id": callback_query["id"], "text": "Unauthorized interaction.", "show_alert": True},
                            timeout=5
                        )
                        continue

                    handle_callback_query(token, callback_query, chat_id)

        except Exception as e:
            logger.error(f"Error in Telegram long-polling loop: {e}")
            time.sleep(5)

def handle_callback_query(token: str, callback_query: dict, chat_id: int):
    query_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    message_id = message.get("message_id")

    # Acknowledge the button tap to Telegram
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={"callback_query_id": query_id},
            timeout=5
        )
    except Exception as e:
        logger.error(f"Error answering callback query: {e}")

    if ":" not in data:
        logger.warning(f"Malformed callback data: {data}")
        return

    action, incident_id = data.split(":", 1)
    db = SessionLocal()
    try:
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            send_telegram_reply(token, chat_id, f"❌ Error: Incident {incident_id} not found in database.")
            return

        if incident.status in ["FIXING", "RESOLVED", "DEFERRED", "IGNORED"]:
            send_telegram_reply(token, chat_id, f"⚠️ Incident for target '{incident.target_id}' is already in status {incident.status}.")
            return

        now = datetime.utcnow()
        if action == "defer":
            incident.deferred_until = now + timedelta(hours=24)
            incident.status = "DEFERRED"
            db.commit()
            send_telegram_reply(token, chat_id, f"⏳ Incident for target '{incident.target_id}' deferred for 24 hours.")
            clear_telegram_message_markup(token, chat_id, message_id)

        elif action == "ignore":
            target = db.query(Target).filter(Target.id == incident.target_id).first()
            if target:
                target.ignored_until = now + timedelta(hours=24)
            incident.status = "IGNORED"
            db.commit()
            send_telegram_reply(token, chat_id, f"🚫 Target '{incident.target_id}' ignored for 24 hours.")
            clear_telegram_message_markup(token, chat_id, message_id)

        elif action == "fix":
            incident.status = "FIXING"
            db.commit()
            send_telegram_reply(token, chat_id, f"🛠️ Remediation approved. Starting execution for '{incident.target_id}'...")
            clear_telegram_message_markup(token, chat_id, message_id)
            
            # Spawn remediation task in a separate background thread
            t = threading.Thread(target=run_remediation_task, args=(incident_id,), daemon=True)
            t.start()

    except Exception as e:
        logger.error(f"Error processing Telegram action '{action}' for incident {incident_id}: {e}")
        send_telegram_reply(token, chat_id, f"❌ Exception encountered while processing request: {e}")
    finally:
        db.close()

def run_remediation_task(incident_id: str):
    try:
        run_remediation(incident_id)
    except Exception as e:
        logger.error(f"Failed to execute remediation for incident {incident_id}: {e}")

def send_telegram_reply(token: str, chat_id: int, text: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
    except Exception as e:
        logger.error(f"Error sending Telegram reply: {e}")

def clear_telegram_message_markup(token: str, chat_id: int, message_id: int):
    url = f"https://api.telegram.org/bot{token}/editMessageReplyMarkup"
    try:
        requests.post(url, json={"chat_id": chat_id, "message_id": message_id, "reply_markup": None}, timeout=5)
    except Exception as e:
        logger.error(f"Error clearing Telegram buttons: {e}")
