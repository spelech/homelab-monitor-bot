# AGENTS.md

This file provides critical context, guidelines, and rules for AI coding agents modifying or debugging the **monitorbot** repository.

---

## Technical Stack & Architecture Context
- **Runtime:** Runs natively on the Linux host (host IP `10.0.0.10`) using system Python 3.11+.
- **Web App Framework:** FastAPI serving HTTP endpoints on port `9013`.
- **Database:** SQLite (`/containers/monitorbot/monitorbot.db`) mapped via SQLAlchemy.
- **RAG Memory:** Local Qdrant instance storing files under `/containers/monitorbot/qdrant_data`.
- **AI Investigation:** Runs the host CLI `agy` (`/home/steve/.local/bin/agy`) in a subprocess.
- **Service Management:** Managed as a host-level systemd service `monitorbot.service`.

---

## Critical Rules & Guidelines

### 1. Git Safety
- The `.gitignore` in this repo is simple but important. Make sure not to commit sensitive credential files, SQLite databases (`*.db`), virtual environments (`venv/`), or Qdrant databases (`qdrant_data/`).
- Always check what files are untracked before committing changes.

### 2. Feedback Loop Prevention
- The Docker event watcher (`watcher.py`) listens to events globally.
- **CRITICAL:** You must never monitor `monitorbot` itself, or `caddy`, as attempting to restart or investigate these within the monitorbot cycle will cause infinite feedback loops or lock out the notification mechanism. Always keep them in the exclusion list:
  ```python
  if "monitorbot" in container_name or container_name == "caddy":
      continue
  ```

### 3. DNS & Domain Unreachability Fallbacks
- **Default URLs:** By default, alerts target `https://ntfy.wileyriley.com` and webhooks target `https://monitorbot.wileyriley.com`.
- **Domain Unreachability:** If the external internet is down, DNS rewrites fail, or the Caddy reverse proxy is stopped, external domain names will fail to resolve.
- **Notifier Fallback Policy:** 
  - If a POST request to `NTFY_URL` fails or times out, the `notifier.py` dispatcher MUST catch the error and retry by posting to `http://localhost:9010` (the host-mapped port for the local `ntfy` container).
  - In the fallback request, the action buttons MUST point to the host's LAN IP `http://10.0.0.10:9013` instead of the external domain. This guarantees that HITL actions can still be clicked and processed via the local network.

### 4. Running and Debugging
- **Venv vs. Host Python:** System-wide packages are already fully installed on the host's python environment (including `fastapi`, `docker`, `sqlalchemy`, `qdrant-client`, `fastembed`, `requests`, `apscheduler`). Use the host `python3` executable rather than the virtual environment if packages are missing inside the venv.
- **Manually starting for test/debug:**
  ```bash
  export PYTHONPATH=/containers/monitorbot
  python3 -m uvicorn app.main:app --host 0.0.0.0 --port 9013
  ```
- **Service Commands:**
  ```bash
  sudo systemctl start monitorbot
  sudo systemctl stop monitorbot
  sudo systemctl status monitorbot
  journalctl -u monitorbot -f
  ```
