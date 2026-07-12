#!/bin/bash
# Startup script for AutoHeal SRE MonitorBot
# Runs uvicorn to serve the FastAPI application on host port 9013

export PYTHONPATH=/containers/monitorbot
cd /containers/monitorbot

# Read configuration from .env if present
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

PORT=${PORT:-9013}
HOST=${HOST:-0.0.0.0}

logger -t monitorbot "Starting AutoHeal SRE MonitorBot on $HOST:$PORT"
exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level info
