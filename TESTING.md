# MonitorBot Testing & Test Coverage Guide

This document details the test suite architecture, testing conventions, test coverage breakdown, and safety procedures for AutoHeal SRE MonitorBot.

---

## 1. Testing Safety & Process Hygiene

### Avoiding Lingering / Runaway Processes
* **Standard Test Runs Must Exclude Live Integration Tests:**
  Always execute non-live unit/integration tests using the `-m "not live"` marker:
  ```bash
  pytest -m "not live"
  ```
* **Live Integration Tests:**
  Tests decorated with `@pytest.mark.live` (e.g. `tests/test_live_executors.py`) invoke external binaries (`opencode`, `agy`, or network services). These tests should only be invoked explicitly when validating live agent execution, and never as part of automated CI or background watchers without timeouts:
  ```bash
  pytest tests/test_live_executors.py -v -s
  ```
* **Mock Subprocesses & Live Network Calls:**
  In all standard tests, mock `subprocess.run`, `subprocess.Popen`, `requests.post`, and Docker SDK operations.
* **Notification Isolation:**
  `tests/conftest.py` contains a global autouse fixture `block_external_notifications` that monkeypatches `app.notifier` dispatch methods across all non-notifier tests to prevent unintended NTFY/SMTP/Telegram broadcasts during test runs.

---

## 2. Test Suite Execution Commands

```bash
# Run all standard unit and integration tests (safely isolated, no live network/agent calls):
pytest -m "not live"

# Run tests with complete statement coverage reporting:
pytest -m "not live" --cov=app --cov-report=term-missing

# Run a specific test module:
pytest tests/test_guardrails.py -v

# Run with verbose output and failure backtraces:
pytest -m "not live" -vv --show-capture=no
```

---

## 3. Test Coverage Matrix

**Overall Coverage: 80% (129 unit & integration tests passing)**

| Module | Statements | Missing | Coverage | Key Tested Capabilities |
| :--- | :---: | :---: | :---: | :--- |
| **`app/ai_usage.py`** | 70 | 3 | **96%** | Token aggregation, cost estimation ($ USD), session logging, summary metrics |
| **`app/database.py`** | 180 | 26 | **86%** | SQLAlchemy models, system settings, maintenance mode state, DB initializers |
| **`app/dependencies.py`** | 72 | 8 | **89%** | Docker client access, Qdrant client lifecycle, auth tokens, DB session injection |
| **`app/investigator.py`** | 225 | 50 | **78%** | Incident triage, AI prompt builder, structured JSON parser, fix sanitization |
| **`app/main.py`** | 157 | 45 | **71%** | FastAPI lifespan, dashboard aggregation `/api/dashboard`, SPA routing fallback |
| **`app/notifier.py`** | 253 | 67 | **74%** | NTFY push dispatcher, SMTP email fallback, Telegram bot integration, action URLs |
| **`app/qdrant_mem.py`** | 76 | 15 | **80%** | FastEmbed vector search, Qdrant collection upsert, RAG memory lookup |
| **`app/remediator.py`** | 158 | 39 | **75%** | Bash remediation runner, guardrails blacklist checks, Uptime Kuma health verification |
| **`app/routers/incidents.py`** | 167 | 30 | **82%** | Incident lifecycle (approve, defer, ignore, retry, unignore), fleet queries |
| **`app/routers/settings.py`** | 48 | 6 | **88%** | Maintenance mode toggle (timed/indefinite/resume), autopilot & silent flags |
| **`app/routers/upgrades.py`** | 65 | 11 | **83%** | Trigger container stack updates, fetch upgrade logs, Canary audit status |
| **`app/routers/usage.py`** | 8 | 0 | **100%** | AI token & spend query API endpoints |
| **`app/scheduler.py`** | 139 | 38 | **73%** | Stale incident renotification, expired target un-ignore, periodic systemd checks |
| **`app/upgrades.py`** | 293 | 48 | **84%** | Autonomous stack pull, compose recreate, prune, 4-phase Canary audit engine |
| **`app/watcher.py`** | 110 | 16 | **85%** | Docker event stream listener, crash detection, circuit breaker suppression |
| **TOTAL** | **2,021** | **402** | **80%** | **129 passed test cases** |

---

## 4. Test Suite Structure

```
tests/
├── conftest.py                      # Shared fixtures (in-memory SQLite, session lifecycle, notification blockers)
├── test_ai_usage.py                 # AI token and spend tracking tests
├── test_auto_approve.py             # Caddy & outage self-healing auto-approval tests
├── test_caddy_suppression.py        # Feedback loop prevention for Caddy & MonitorBot
├── test_coverage_boost.py           # Legacy fallback and edge-case coverage
├── test_final_push.py               # Outage recovery & LAN fallback endpoints
├── test_guardrails.py               # Command blacklist & destructive action blockers
├── test_investigator_full.py        # Investigation flow and status transitions
├── test_investigator_parser.py      # LLM output JSON extraction and sanitization
├── test_live_executors.py           # Live E2E tests for OpenCode & AGY binaries (@pytest.mark.live)
├── test_main.py                     # Webhook endpoints & health check routes
├── test_main_extended.py            # API dashboard serialization & count metrics
├── test_maintenance.py              # Maintenance mode (timed, indefinite, resume) & CLI
├── test_mcp.py                      # MCP server tool definitions and execution
├── test_more_coverage.py            # Remediator health probes & dependency checks
├── test_notifier.py                 # NTFY dispatching and localhost fallback
├── test_notifier_email.py           # SMTP email dispatching and diagnostics formatting
├── test_notifier_extended.py        # Action button formatting & multi-channel routing
├── test_prompts.py                  # Domain-specific prompt templates and triage rules
├── test_qdrant_extended.py          # Vector database persistence and similarity scoring
├── test_remediator_full.py          # Remediation execution, subprocess handling, and timeouts
├── test_routers_incidents.py        # Incident router REST endpoints
├── test_scheduler.py                # Deferred incident retry & un-ignore expiration
├── test_scheduler_extended.py       # Stale notification reminders
├── test_scheduler_watcher_boost.py  # Periodic scheduler sweeps
├── test_upgrades.py                 # Upgrade workflow lifecycle & Canary audit
├── test_upgrades_extended.py        # Upgrade API endpoints and history
├── test_watcher_full.py             # Docker event ingestion and circuit breaker logic
└── test_watcher_remediator_deep.py  # Systemd failure handling and remediation
```

---

## 5. Adding New Tests
1. **Always use fixtures:** Use the `db_session` fixture for database isolation.
2. **Never execute live commands:** Mock `subprocess.run` / `subprocess.Popen` in unit tests.
3. **Maintain coverage standards:** Keep per-module coverage $\ge 75\%$ and aggregate coverage $\ge 80\%$.
