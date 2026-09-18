# Configuration & CLI Reference

MonitorBot is configured via environment variables defined in `/containers/monitorbot/.env`. The service runs natively on the Linux host managed by **systemd**, and provides a command-line interface (`cli.py`) for management and diagnostics.

---

## Environment Variables Reference (`.env`)

### 1. Web & Database Configuration

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `HOST` | `0.0.0.0` | Bind IP address for FastAPI / Uvicorn server. |
| `PORT` | `9013` | Bind port on the host network. |
| `DATABASE_URL` | `sqlite:///./monitorbot.db` | SQLAlchemy connection string for SQLite database. |
| `WEBHOOK_BASE_URL` | `https://monitorbot.wileyriley.com` | Public HTTPS URL for incoming webhooks and action buttons. |
| `LOCAL_WEBHOOK_BASE_URL` | `http://10.0.0.10:9013` | Fallback LAN base URL used when external reverse proxy is down. |
| `WEBHOOK_TOKEN` | *Required* | Shared secret token required for authenticating webhook action endpoints. |

---

### 2. AI Delegation & Model Execution

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `AI_DISPATCH_URL` | `http://localhost:8032/v1` | URL for CLIAgentDispatch OpenAI-compatible HTTP gateway. |
| `AI_MODEL` | `opencode` | Model identifier or alias (`opencode`, `agy`, `litellm/qwen3.7-flash`). |
| `AI_DISPATCH_TIMEOUT`| `180` | Seconds to wait before falling back to local CLI subprocess. |
| `AI_EXECUTOR` | `opencode` | Primary fallback executor (`opencode` or `agy`). |
| `OPENCODE_SERVER_URL`| `http://localhost:4096` | Headless OpenCode HTTP daemon endpoint. |
| `OPENCODE_MODEL` | `litellm/qwen3.7-flash` | Default model passed to OpenCode. |
| `OPENCODE_PATH` | `/home/steve/.nvm/.../opencode` | Absolute path to OpenCode binary. |
| `AGY_PATH` | `/home/steve/.local/bin/agy` | Absolute path to Antigravity CLI binary. |
| `AGY_MODEL` | `Gemini 3.5 Flash (Medium)` | Model configuration string passed to `agy`. |

---

### 3. Vector Memory (Qdrant & FastEmbed)

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `QDRANT_URL` | *None* (local file) | If set (e.g. `http://localhost:8010`), connects to remote Qdrant container. |
| `QDRANT_PATH` | `./qdrant_data` | Directory for embedded local file storage when `QDRANT_URL` is empty. |

---

### 4. Push Notifications & Interactive Alerts (ntfy)

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `NTFY_URL` | `https://ntfy.wileyriley.com` | Primary public ntfy server URL. |
| `NTFY_TOPIC` | `alerts` | Topic name for incident notifications. |
| `NTFY_USER` | `steve` | Basic Auth username for protected ntfy topics. |
| `NTFY_PASS` | *Optional* | Basic Auth password for protected ntfy topics. |
| `NTFY_FALLBACK_URL` | `http://localhost:9010` | Direct local container fallback URL when public domain is down. |
| `NOTIFICATION_PRIORITY` | `max` | ntfy priority for new incident alerts (`min`, `low`, `default`, `high`, `max`). |
| `FOLLOWUP_NOTIFICATION_PRIORITY` | `high` | ntfy priority for resolution / follow-up notifications. |

---

### 5. Emergency SMTP Email Fallback

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `SMTP_SERVER` | `smtp.gmail.com` | Outbound mail server hostname. |
| `SMTP_PORT` | `465` (SSL) / `587` (TLS) | Outbound SMTP port. |
| `SMTP_USER` | *Required for email* | SMTP account username / email address. |
| `SMTP_PASS` | *Required for email* | App-specific password for SMTP authentication. |
| `EMAIL_FROM` | Defaults to `SMTP_USER` | Sender address on incident notifications. |
| `EMAIL_TO` | `steven.pelech@gmail.com` | Destination recipient address for emergency digests. |

---

### 6. Telegram Bot Alerts

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | *Optional* | Bot authorization token from @BotFather. |
| `TELEGRAM_CHAT_ID` | *Optional* | Telegram target chat or group ID. |

---

### 7. Storage & Schedule Configuration

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `MONITORED_MOUNTS` | *Dynamic discovery* | Comma-separated list of explicit mount paths to monitor. |
| `MONITOR_SYSTEMD_SERVICES` | *None* | Comma-separated list of non-Docker host services (e.g. `ssh,plex`). |
| `HEARTBEAT_INTERVAL_HOURS` | `4` | Frequency of green heartbeat check-in alerts. |
| `SRE_AUDIT_CRON_HOUR` | `3` | Hour of day (0-23 UTC) to run scheduled 24-hour stack log audits. |
| `SRE_AUDIT_CRON_MINUTE` | `0` | Minute (0-59 UTC) to run scheduled 24-hour stack log audits. |

---

## Systemd Service Management

MonitorBot runs as a persistent host service defined in `/etc/systemd/system/monitorbot.service` (or repository link `/containers/monitorbot/monitorbot.service`):

```ini
[Unit]
Description=AutoHeal SRE MonitorBot
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=steve
WorkingDirectory=/containers/monitorbot
EnvironmentFile=/containers/monitorbot/.env
ExecStart=/bin/bash /containers/monitorbot/run.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Lifecycle Commands

```bash
# Check service status and health
sudo systemctl status monitorbot

# Start or restart MonitorBot
sudo systemctl start monitorbot
sudo systemctl restart monitorbot

# Stop the service
sudo systemctl stop monitorbot

# View live streaming systemd journal logs
journalctl -u monitorbot -f
```

---

## Command-Line Interface (`cli.py`)

MonitorBot includes a CLI tool (`cli.py`) located in `/containers/monitorbot`:

```bash
python3 cli.py <command> [arguments]
```

### Command Reference

#### 1. System Status & Settings
```bash
# View active monitoring state, autopilot flag, and maintenance status
python3 cli.py status

# Enable / disable silent monitoring mode (suppresses alerts and automated fixes)
python3 cli.py silent on
python3 cli.py silent off

# Enable / disable autopilot mode (automatically executes AI fixes without human prompt)
python3 cli.py autopilot on
python3 cli.py autopilot off
```

#### 2. Maintenance Mode Controls
```bash
# Pause monitoring for a specific duration
python3 cli.py pause 15m
python3 cli.py pause 30m
python3 cli.py pause 2h

# Pause monitoring indefinitely
python3 cli.py pause indefinite

# Resume normal active monitoring
python3 cli.py resume
```

#### 3. Vector Memory Management (Qdrant)
```bash
# List all learned historical incidents and verified commands
python3 cli.py memory list

# Perform semantic similarity search against past fixes
python3 cli.py memory search "failed to bind port"

# Manually insert a verified fix into Qdrant memory
python3 cli.py memory learn \
  --target "traefik" \
  --cause "Port 80 occupied by stray apache process" \
  --fix "systemctl stop apache2 && docker compose restart traefik"
```

#### 4. Diagnostic Prompt Testing
```bash
# Test an investigation prompt against live AI executors without creating an incident
python3 cli.py test-prompt \
  --target "kopia" \
  --error "runtime error: connection refused on port 51515" \
  --history "docker compose restart kopia"
```
