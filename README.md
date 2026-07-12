# AutoHeal SRE MonitorBot (L3 Autonomous SRE Assistant)

AutoHeal is an event-driven Python application designed to run natively on a Linux host. It monitors Docker containers, utilizes the `agy` (Antigravity) CLI via subprocesses to investigate failures and propose fixes, and coordinates human-in-the-loop (HITL) approvals via `ntfy` push notifications. It features a RAG (Retrieval-Augmented Generation) memory system using Qdrant to learn from past incidents.

## Features

- **Non-Polling Docker Monitor:** Listens to the Docker daemon event stream for container crashes (`die` events with non-zero exit codes) or container `health_status: unhealthy` events.
- **Autonomous AI Investigator:** Invokes the local `agy` CLI in a subprocess to analyze container logs, identify the root cause, and propose a bash-script remediation command.
- **Semantic Memory (RAG):** Integrates Qdrant vector database using `fastembed` to store successful incident resolutions and inject historical solutions as context if similar errors occur in the future.
- **Interactive Push Alerts:** Delivers rich push notifications using `ntfy` with Action Buttons, allowing administrators to approve fixes, defer alerts, or ignore targets directly from their mobile devices or desktop.
- **Web Dashboard:** Serves an interactive HTML dashboard built with FastAPI, SQLAlchemy (SQLite), and Tailwind CSS to track active incidents, view resolution histories, and manage target ignore/defer states.

---

## Directory Structure

```
monitorbot/
├── app/
│   ├── database.py       # SQLAlchemy database schema and session management
│   ├── investigator.py   # AI subprocess executor calling agy CLI
│   ├── main.py           # FastAPI entrypoint and HTTP API routes
│   ├── notifier.py       # ntfy notification dispatcher with fallback support
│   ├── qdrant_mem.py     # Qdrant client vector store & semantic search
│   ├── remediator.py     # Auto-remediation script and health verification
│   ├── scheduler.py      # APScheduler job to manage deferred/ignored targets
│   ├── watcher.py        # Non-polling Docker SDK event stream listener
│   └── templates/
│       └── index.html    # Web dashboard UI
├── .env                  # Configuration variables
├── .env.example          # Sample environment variables
├── monitorbot.service    # Systemd service configuration file
├── run.sh                # Application startup script
└── README.md             # This file
```

---

## Technical Architecture

```mermaid
graph TD
    Docker[Docker Daemon] -->|die/unhealthy| Watcher[watcher.py]
    Watcher -->|Insert DETECTED| DB[(SQLite DB)]
    Watcher -->|Trigger| Investigator[investigator.py]
    Investigator -->|Search similar| Qdrant[(Qdrant DB)]
    Investigator -->|Subprocess| Agy[agy CLI]
    Agy -->|Proposed Fix JSON| Investigator
    Investigator -->|Update PENDING_USER| DB
    Investigator -->|Dispatch| Notifier[notifier.py]
    Notifier -->|Push notification| Ntfy[ntfy.sh Server]
    Ntfy -->|HITL Action| Webhook[main.py webhook API]
    Webhook -->|Approved 'fix'| Remediator[remediator.py]
    Remediator -->|Run proposed bash fix| Host[Linux Host]
    Remediator -->|Verify health| Docker
    Remediator -->|RESOLVED / FAILED| DB
    Remediator -->|Save resolution| Qdrant
    Remediator -->|Follow-up| Notifier
```

---

## Configuration & Environment Variables

Create a `.env` file in the root of the repository:

```env
DATABASE_URL=sqlite:////containers/monitorbot/monitorbot.db
NTFY_URL=https://ntfy.wileyriley.com
NTFY_TOPIC=alerts
NTFY_USER=your_ntfy_username
NTFY_PASS=your_ntfy_password
WEBHOOK_BASE_URL=https://your-monitorbot-domain.com
WEBHOOK_TOKEN=your_secure_webhook_token
PORT=9013
HOST=0.0.0.0
AGY_PATH=/home/steve/.local/bin/agy
```

---

## Setup & Running

### Natively on Host
1. **Initialize and Activate Virtual Environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt # (or install dependencies: fastapi uvicorn docker sqlalchemy qdrant-client fastembed requests apscheduler jinja2)
   ```
2. **Run manually:**
   ```bash
   ./run.sh
   ```

### Managing via systemd
To run MonitorBot continuously as a systemd service:
1. **Install service unit:**
   ```bash
   sudo cp monitorbot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```
2. **Enable and Start:**
   ```bash
   sudo systemctl enable monitorbot.service
   sudo systemctl start monitorbot.service
   ```
3. **Verify Status:**
   ```bash
   systemctl status monitorbot.service
   journalctl -u monitorbot.service -f
   ```

---

## Resiliency Features

### Local Failover & Unreachable Domains
In the event that external domain resolution, internet access, or the Caddy reverse proxy is down:
1. **Local ntfy Fallback:** If `NTFY_URL` (e.g. `https://ntfy.wileyriley.com`) is unreachable, the system automatically falls back to `http://localhost:9010` (the host-mapped port for the local `ntfy` container) to deliver the alert locally.
2. **Local Webhook URL Actions:** The fallback push alerts contain Action buttons that point directly to the host's LAN IP (`http://10.0.0.10:9013`) instead of the external subdomain, ensuring approvals can be processed on the local network.
