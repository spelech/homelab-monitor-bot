# REST API Reference

MonitorBot exposes a comprehensive RESTful API built with **FastAPI** running on port `9013`. The API powers the React SPA dashboard, CLI tools, external webhooks, and automation scripts.

All JSON endpoints reside under the `/api` prefix.

---

## Authentication & Security

- **Webhooks (`/api/webhooks/*`)**: Require a secret token passed as a query parameter (`?token=<WEBHOOK_TOKEN>`).
- **Dashboard & Management Endpoints**: Designed for protected LAN operation (`10.0.0.10`) or behind Caddy reverse proxy authenticated via TinyAuth SSO (`Remote-User` / OIDC headers).

---

## Dashboard Overview

### `GET /api/dashboard`
Aggregates unified system status, incident counters, maintenance states, and recent history into a single low-latency payload.

#### Response (`200 OK`)
```json
{
  "active_count": 1,
  "resolved_count": 142,
  "targets_count": 48,
  "ignored_count": 2,
  "active_incidents": [
    {
      "id": "e4b11f32-8dfb-4654-a6ec-071a39beecf7",
      "target_id": "paperless-ngx",
      "status": "PENDING_USER",
      "category": "database",
      "error_logs": "FATAL: connection to server at 'postgres' failed: Connection refused",
      "root_cause": "PostgreSQL database container was restarting during paperless boot.",
      "proposed_fix": "cd /containers/cloud && docker compose restart paperless-ngx",
      "execution_log": null,
      "completed_at": null,
      "created_at": "2026-09-17T14:23:10.120000"
    }
  ],
  "ignored_targets": [
    {
      "id": "mount:/mnt/backup-cold",
      "type": "system_mount",
      "ignored_until": "9999-12-31T23:59:59"
    }
  ],
  "history_incidents": [],
  "maintenance_active": false,
  "maintenance_reason": "",
  "autopilot": false,
  "silent_mode": false
}
```

---

## Incidents & Targets

### `GET /api/incidents/active`
Lists all unresolved incidents (`DETECTED`, `INVESTIGATING`, `PENDING_USER`, `FIXING`, `BLOCKED`).

#### Response (`200 OK`)
Array of incident objects ordered by `created_at` descending.

---

### `GET /api/incidents/history`
Retrieves past resolved, failed, or dismissed incidents.

#### Parameters
| Parameter | Type | In | Description | Default |
| :--- | :--- | :--- | :--- | :--- |
| `limit` | integer | Query | Maximum historical incidents to return | `100` |

---

### `GET /api/incidents/search`
Executes semantic vector similarity search via Qdrant memory across resolved incidents.

#### Parameters
| Parameter | Type | In | Description | Required |
| :--- | :--- | :--- | :--- | :--- |
| `q` | string | Query | Natural language error query or symptom | **Yes** |
| `limit` | integer | Query | Maximum results to return | `10` |

#### Response (`200 OK`)
```json
[
  {
    "id": "3a12cd6b-8714-4632-95b1-12f716aa831b",
    "target_id": "authentik-server",
    "status": "RESOLVED",
    "category": "database",
    "root_cause": "Postgres connection pool exhausted.",
    "proposed_fix": "cd /containers/webservices && docker compose restart authentik-server",
    "completed_at": "2026-09-12T04:12:00",
    "score": 0.8412
  }
]
```

---

### `POST /api/incidents/{incident_id}/action`
Executes a triage action against an active incident.

#### Request Body
```json
{
  "action": "fix"
}
```

| Action String | Description |
| :--- | :--- |
| `"fix"` | Spawns background remediation worker to execute `proposed_fix`. |
| `"defer"` | Snoozes incident alerts for 24 hours (`status="DEFERRED"`). |
| `"ignore"` | Permanently ignores the target container (`target.ignored_until=9999-12-31`). |
| `"dismiss"` | Manually resolves incident without command execution (`status="RESOLVED"`). |

#### Response (`200 OK`)
```json
{
  "status": "ok",
  "detail": "Remediation triggered"
}
```

---

### `GET /api/incidents/{incident_id}/transcript`
Returns the chronological audit trail of internal engine events for the incident.

#### Response (`200 OK`)
```json
{
  "incident_id": "e4b11f32-8dfb-4654-a6ec-071a39beecf7",
  "target_id": "paperless-ngx",
  "events": [
    {
      "event_type": "PROMPT_GENERATED",
      "timestamp": "2026-09-17T14:23:12",
      "data": { "prompt": "... full prompt text ..." }
    },
    {
      "event_type": "AI_THINKING_RAW",
      "timestamp": "2026-09-17T14:23:16",
      "data": { "executor": "dispatch", "exec_duration": 4.12 }
    },
    {
      "event_type": "DIAGNOSIS_PARSED",
      "timestamp": "2026-09-17T14:23:16",
      "data": { "category": "database", "auto_approve": false }
    }
  ]
}
```

---

### `GET /api/targets`
Returns all monitored targets (containers, systemd services, storage mounts) with live Docker daemon health states.

#### Response (`200 OK`)
```json
[
  {
    "id": "caddy",
    "type": "docker",
    "is_ignored": false,
    "ignored_until": null,
    "docker_status": "running",
    "docker_health": "healthy"
  }
]
```

---

### `POST /api/targets/{target_id}/unignore`
Removes ignore suppression from a target, re-enabling active surveillance.

---

## Webhooks (ntfy & Terminal Integration)

### `GET|POST /api/webhooks/{incident_id}`
Token-authenticated endpoint designed for ntfy interactive action buttons, curl requests, and email links.

#### Query Parameters
| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `token` | string | **Yes** | Must match `WEBHOOK_TOKEN` in `.env`. |
| `action` | string | Optional | Action (`fix`, `defer`, `ignore`) when submitted via GET/query. |

#### Request Body (POST, `application/json`)
```json
{
  "action": "fix"
}
```

#### Pre-Execution Health Verification
Before triggering remediation, the webhook handler verifies whether the target has already recovered on its own. If verified running and healthy, the incident is auto-resolved without running redundant commands.

---

## Docker Stacks & SRE Auditing

### `GET /api/stacks`
Discovers all Docker Compose stacks on the host with container status, available registry updates, and last SRE audit results.

---

### `GET /api/stacks/{stack_name}`
Returns detailed inventory for a specific stack, including individual containers, port bindings, audit history, and recent incidents.

---

### `POST /api/stacks/audit-all`
Triggers an asynchronous SRE log review across all discovered Docker Compose stacks.

---

### `POST /api/stacks/{stack_name}/audit`
Triggers an on-demand SRE log audit for a single stack.

---

### `POST /api/stacks/{stack_name}/check-updates`
Queries remote container registries for image digest updates across all containers in the stack.

---

## Canary Upgrades & System Lifecycle

### `GET /api/upgrades/stacks`
Returns list of stacks eligible for autonomous upgrade management.

---

### `POST /api/upgrades/run`
Initiates an asynchronous full-stack or targeted upgrade workflow.

#### Request Body
```json
{
  "targets": ["media_download", "webservices"]
}
```
*Pass `["all"]` or `null` to upgrade all stacks.*

---

### `GET /api/upgrades/live`
Polls live progress, streaming log output, and phase status of the currently active upgrade job.

---

### `POST /api/upgrades/cancel`
Requests graceful cancellation of the running upgrade job.

---

### `POST /api/upgrades/canary`
Executes an immediate standalone 4-phase Canary Health & Routing audit without pulling or restarting images:
1. Container crash loop and restart check.
2. Container health status probe (`unhealthy` filter).
3. Caddy reverse proxy syntax and routing validation (`caddy validate`).
4. Core HTTPS domain reachability checks.

---

### `GET /api/upgrades/runs`
Lists historical upgrade runs with timestamps and canary audit results.

---

### `GET /api/upgrades/runs/{run_id}`
Retrieves complete execution logs and canary check details for a past upgrade run.

---

## Settings, Maintenance & Usage

### `GET /api/settings`
Returns operational mode flags and maintenance status.

---

### `POST /api/settings`
Updates system flags:
```json
{
  "silent_mode": false,
  "autopilot": true
}
```

---

### `POST /api/maintenance`
Enables or disables maintenance mode suppression:
```json
{
  "duration": "30m"
}
```
*Values: `"15m"`, `"30m"`, `"1h"`, `"2h"`, `"12h"`, `"indefinite"`, `"resume"`.*

---

### `GET /api/usage/summary`
Returns cumulative token metrics, AI spending breakdown, and executor call counts.
