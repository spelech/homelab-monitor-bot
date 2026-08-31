"""
Structured JSONL Transcript & Thinking Logger for MonitorBot.
Records AI prompt generation, raw model reasoning/thinking tokens, parsed diagnoses,
remediation execution steps, and post-action verification in per-incident transcripts.
"""

import os
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("TranscriptLogger")

_file_locks: Dict[str, threading.Lock] = {}
_global_lock = threading.Lock()


def _get_lock(incident_id: str) -> threading.Lock:
    with _global_lock:
        if incident_id not in _file_locks:
            _file_locks[incident_id] = threading.Lock()
        return _file_locks[incident_id]


def get_transcript_dir() -> str:
    return os.getenv("TRANSCRIPT_DIR", "/containers/monitorbot/logs/transcripts")


def ensure_transcript_dir():
    d = get_transcript_dir()
    try:
        os.makedirs(d, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create transcript directory '{d}': {e}")


def get_transcript_path(incident_id: str) -> str:
    ensure_transcript_dir()
    # Sanitize incident_id to prevent directory traversal
    clean_id = "".join(c for c in incident_id if c.isalnum() or c in ("-", "_"))
    return os.path.join(get_transcript_dir(), f"{clean_id}.jsonl")


def log_transcript_event(incident_id: Optional[str], event_type: str, data: Dict[str, Any]) -> None:
    """
    Appends a structured event object to the incident's JSONL transcript file.
    """
    if not incident_id:
        return

    filepath = get_transcript_path(incident_id)
    lock = _get_lock(incident_id)

    event_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "data": data,
    }

    try:
        with lock:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(event_payload) + "\n")
    except Exception as e:
        logger.error(f"Failed to write transcript event for incident '{incident_id}': {e}")


def get_transcript(incident_id: str) -> List[Dict[str, Any]]:
    """
    Reads and parses all events from the incident's JSONL transcript.
    """
    filepath = get_transcript_path(incident_id)
    if not os.path.exists(filepath):
        return []

    events = []
    lock = _get_lock(incident_id)
    try:
        with lock:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        continue
    except Exception as e:
        logger.error(f"Failed to read transcript for incident '{incident_id}': {e}")
        return []

    return events
