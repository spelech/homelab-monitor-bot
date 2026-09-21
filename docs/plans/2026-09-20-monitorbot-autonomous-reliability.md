# MonitorBot Autonomous Reliability & Alert Noise Elimination Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate out-of-date 3:00 AM alerts, resolve the race condition causing instant incident auto-resolutions, and enable reliable autonomous self-healing for container crashes and low-risk failures.

**Architecture:** 
1. Separate daily 24h historical log analysis from active incident alerting: healthy running containers with historical warnings are aggregated into a single morning SRE digest instead of triggering individual push notifications.
2. In the background scheduler, eliminate the instant auto-resolve race condition by preventing premature closure of pending incidents.
3. In the remediation pipeline, sanitize LLM output to extract pure executable shell commands and prevent bash syntax errors.
4. In the Docker event watcher, introduce crash-loop/flapping detection so single clean restarts handled by Docker are noted without firing false alarms.
5. In the investigator and remediator, provide tiered autopilot safety to autonomously execute low-risk recovery actions (like `docker compose restart <service>`) when enabled.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, APScheduler, Docker SDK for Python, Pytest.

## Global Constraints
- Target repository: `/containers/monitorbot` on branch `feature/monitorbot-reliability`.
- Preserves all existing database schemas (`Incident`, `Target`, `StackAudit`, `SystemSetting`).
- Pytest test suite must exclude live markers (`pytest -m "not live"`).
- Containers and services must remain immutable; never inject code into running containers.
- Backward compatibility for existing ntfy webhooks and REST endpoints.

---

### Task 1: Audit Alerting & Morning Digest (Eliminate 3:00 AM Alert Floods)

**Files:**
- Modify: `app/stack_watcher.py:530-865`
- Modify: `app/scheduler.py:204-225`
- Modify: `app/notifier.py`
- Test: `tests/test_audit_digest.py`

**Interfaces:**
- `audit_stack_logs(stack_name: str, db: Optional[Session] = None) -> Dict[str, Any]`
- `send_sre_digest_notification(results: List[Dict[str, Any]]) -> bool`

- [ ] **Step 1: Write failing test for SRE audit suppression on healthy containers**

```python
# tests/test_audit_digest.py
import pytest
from unittest.mock import MagicMock, patch
from app.stack_watcher import StackWatcherManager

def test_audit_stack_logs_healthy_container_does_not_create_pending_incident(db_session):
    client = MagicMock()
    container = MagicMock()
    container.name = "radarr4k"
    container.attrs = {
        "Config": {"Labels": {"com.docker.compose.project": "media_content"}},
        "State": {"Running": True, "Health": {"Status": "healthy"}}
    }
    container.logs.return_value = b"2026-09-20 02:00:00 [WRN] Failed to query remote API\n"
    client.containers.list.return_value = [container]

    manager = StackWatcherManager(client=client)
    with patch("app.stack_watcher.call_sre_ai_analyst") as mock_ai:
        mock_ai.return_value = '{"containers": {"radarr4k": {"root_cause": "API timeout", "proposed_fix": "docker compose restart radarr4k", "action_required": false}}}'
        result = manager.audit_stack_logs("media_content", db=db_session)
    
    assert result["status"] in ["HEALTHY", "WARNING"]
    assert result.get("incident_ids") == []
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_audit_digest.py -v`
Expected: FAIL (file does not exist yet)

- [ ] **Step 3: Implement SRE audit status check and digest notification**
In `app/stack_watcher.py`:
1. When checking `stack_containers`, determine if container is currently running & healthy.
2. If the container is currently running and healthy, even if 24h logs contain non-benign warnings, set `action_required = False` unless the container has explicitly crashed or is degraded.
3. In `audit_all_stacks()`, do not fire individual `send_incident_notification` for each stack. Instead, collect summary metrics and send a single morning digest via `notifier.send_sre_digest_notification()`.

In `app/notifier.py`:
Implement `send_sre_digest_notification(results: List[Dict[str, Any]])` to send a single consolidated summary:
`"📊 Daily SRE Audit: 23 stacks checked. 0 active outages. X warnings logged."` with tag `clipboard`.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_audit_digest.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**
```bash
git add app/stack_watcher.py app/scheduler.py app/notifier.py tests/test_audit_digest.py
git commit -m "feat(audit): replace 3am individual incident alerts with daily SRE summary digest"
```

---

### Task 2: Fix Scheduler Auto-Resolve Race Condition

**Files:**
- Modify: `app/scheduler.py:40-95`
- Test: `tests/test_scheduler_race.py`

**Interfaces:**
- `check_deferred_and_ignored()`

- [ ] **Step 1: Write failing test for auto-resolve race condition**

```python
# tests/test_scheduler_race.py
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from app.database import Incident, Target
from app.scheduler import check_deferred_and_ignored

def test_sre_audit_incident_not_auto_resolved_prematurely(db_session):
    # Incident created by sre_daily_audit should not be resolved 30 seconds later
    inc = Incident(
        id="test-audit-inc-1",
        target_id="prowlarr",
        status="PENDING_USER",
        origin="sre_daily_audit",
        root_cause="Stale endpoint config",
        proposed_fix="docker compose restart prowlarr",
        created_at=datetime.utcnow() - timedelta(seconds=30)
    )
    db_session.add(inc)
    db_session.commit()

    docker_mock = MagicMock()
    container_mock = MagicMock()
    container_mock.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
    docker_mock.containers.get.return_value = container_mock

    with patch("docker.from_env", return_value=docker_mock):
        check_deferred_and_ignored()

    refreshed = db_session.query(Incident).filter(Incident.id == "test-audit-inc-1").first()
    # It should not have been auto-resolved instantly
    assert refreshed.status == "PENDING_USER"
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_scheduler_race.py -v`
Expected: FAIL (refreshed.status == "RESOLVED")

- [ ] **Step 3: Update scheduler auto-resolve policy**
In `app/scheduler.py`:
1. Check `incident.origin`. If `incident.origin == "sre_daily_audit"`, do not auto-resolve simply because the container is running (the container was already running when the audit was created).
2. For reactive incidents, only auto-resolve if the incident has been open for at least 3 minutes and the target has been continuously healthy, preventing the 30-second race.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_scheduler_race.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**
```bash
git add app/scheduler.py tests/test_scheduler_race.py
git commit -m "fix(scheduler): prevent premature auto-resolution of audit incidents"
```

---

### Task 3: Remediation Command Sanitization & Robust Bash Execution

**Files:**
- Modify: `app/remediator.py:14-115`
- Modify: `app/prompts.py:55-64`
- Test: `tests/test_remediation_sanitizer.py`

**Interfaces:**
- `sanitize_remediation_command(proposed_fix: str) -> str`
- `run_remediation(incident_id: str)`

- [ ] **Step 1: Write failing test for command sanitization**

```python
# tests/test_remediation_sanitizer.py
import pytest
from app.remediator import sanitize_remediation_command

def test_sanitize_markdown_fences():
    raw = "```bash\ncd /containers/media_content && docker compose restart radarr4k\n```"
    clean = sanitize_remediation_command(raw)
    assert clean == "cd /containers/media_content && docker compose restart radarr4k"

def test_sanitize_numbered_bullets():
    raw = "1. Restart Radarr4K to clear error: cd /containers/media_content && docker compose restart radarr4k\n2. Verify health: ping 10.0.0.10"
    clean = sanitize_remediation_command(raw)
    assert "1. Restart" not in clean
    assert "cd /containers/media_content && docker compose restart radarr4k" in clean

def test_sanitize_trailing_commentary():
    raw = "cd /containers/cameras && docker compose up -d --force-recreate frigate\nIf this fails, check logs."
    clean = sanitize_remediation_command(raw)
    assert clean.startswith("cd /containers/cameras && docker compose up -d --force-recreate frigate")
    assert "If this fails" not in clean
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_remediation_sanitizer.py -v`
Expected: FAIL (function does not exist)

- [ ] **Step 3: Implement `sanitize_remediation_command` and update `app/prompts.py`**
In `app/remediator.py`:
1. Add `sanitize_remediation_command(proposed_fix: str) -> str`:
   - Strip code fences (````bash ... ```` or ````sh ... ````).
   - Filter lines: extract executable shell statements (starting with common shell binaries: `docker`, `docker compose`, `systemctl`, `cd`, `curl`, `chown`, `chmod`, `rm`, `kill`, `fusermount`, `umount`, etc.).
   - Strip leading numbers (`1. `, `1) `) and bullet markers (`- `).
   - Discard non-executable commentary lines.
2. In `app/prompts.py`, update `REMEDIATION_PLAN_CONTRACT` with explicit directive:
   `"CRITICAL: 'proposed_fix' MUST contain ONLY executable bash commands. Do NOT include markdown code blocks, conversational explanations, or numbered bullet points inside 'proposed_fix'."`

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_remediation_sanitizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**
```bash
git add app/remediator.py app/prompts.py tests/test_remediation_sanitizer.py
git commit -m "feat(remediator): sanitize LLM proposed fixes to ensure clean bash execution"
```

---

### Task 4: Flapping and Crash-Loop Detection in Watcher

**Files:**
- Modify: `app/watcher.py:43-179`
- Test: `tests/test_watcher_flapping.py`

**Interfaces:**
- `is_container_crash_looping(container_name: str, exit_code: str) -> bool`

- [ ] **Step 1: Write failing test for single restart vs crash-loop**

```python
# tests/test_watcher_flapping.py
import pytest
from app.watcher import CrashTracker

def test_single_clean_restart_is_not_crash_loop():
    tracker = CrashTracker()
    assert tracker.record_and_check_crash_loop("matter-hub", "1") is False

def test_repeated_crash_is_crash_loop():
    tracker = CrashTracker()
    tracker.record_and_check_crash_loop("matter-hub", "1")
    assert tracker.record_and_check_crash_loop("matter-hub", "1") is True
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_watcher_flapping.py -v`
Expected: FAIL (CrashTracker not defined)

- [ ] **Step 3: Implement `CrashTracker` in `app/watcher.py`**
1. Track container exit events in a 5-minute sliding window.
2. If exit code is 0, 143, or 130: ignore.
3. If container dies once, allow 3 seconds for Docker's restart policy to restart it. If Docker brings it back healthy immediately, log info and do not create an active incident.
4. If container crashes again within 5 minutes or stays down after 3 seconds, mark as crash-loop / failure and create the incident.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_watcher_flapping.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**
```bash
git add app/watcher.py tests/test_watcher_flapping.py
git commit -m "feat(watcher): add crash tracker to handle transient Docker restarts gracefully"
```

---

### Task 5: Tiered Autopilot for Safe Independent Remediation

**Files:**
- Modify: `app/investigator.py:305-350`
- Modify: `app/database.py`
- Test: `tests/test_safe_autopilot.py`

**Interfaces:**
- `is_fix_safe_for_autopilot(command: str, category: str) -> bool`

- [ ] **Step 1: Write failing test for safe autopilot tiering**

```python
# tests/test_safe_autopilot.py
import pytest
from app.investigator import is_fix_safe_for_autopilot

def test_low_risk_restart_is_safe_for_autopilot():
    cmd = "docker compose -f /containers/media_content/docker-compose.yaml restart radarr4k"
    assert is_fix_safe_for_autopilot(cmd, "api_error") is True

def test_destructive_command_not_safe_for_autopilot():
    cmd = "rm -f /containers/media_content/radarr/config.xml && docker restart radarr4k"
    assert is_fix_safe_for_autopilot(cmd, "config") is False
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_safe_autopilot.py -v`
Expected: FAIL (is_fix_safe_for_autopilot not defined)

- [ ] **Step 3: Implement safe autopilot classifier and allow low-risk auto-remediation**
In `app/investigator.py`:
1. Define `is_fix_safe_for_autopilot(command: str, category: str) -> bool`:
   - Returns `True` for standard non-destructive compose commands (`docker compose restart <service>`, `docker compose up -d <service>`, `systemctl restart <service>`).
   - Returns `False` for file modifications, deletions, or unknown scripts.
2. In `run_investigation_logic`:
   - If `autopilot` is enabled (or `autopilot_safe_mode == "true"`), and `is_fix_safe_for_autopilot(proposed_fix)` is `True`, auto-approve the incident (`status = "FIXING"`), notify the user that auto-healing is in progress, and trigger remediation.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_safe_autopilot.py -v`
Expected: PASS

- [ ] **Step 5: Commit changes**
```bash
git add app/investigator.py tests/test_safe_autopilot.py
git commit -m "feat(investigator): add safe autopilot tiering for low-risk container restarts"
```

---

### Task 6: Full Regression Verification & Live Test

**Files:**
- Test: All tests in `tests/`

- [ ] **Step 1: Run full test suite**
Run: `pytest -m "not live"`
Expected: All tests pass (229+ tests)

- [ ] **Step 2: Verify service health and syntax**
Run:
```bash
python3 -c "import app.main; print('MonitorBot modules load successfully')"
```

- [ ] **Step 3: Final commit and summary**
Commit any remaining docs or cleanup.
