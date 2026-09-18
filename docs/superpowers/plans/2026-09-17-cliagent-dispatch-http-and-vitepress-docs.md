# CLIAgentDispatch HTTP Integration & VitePress Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor MonitorBot's AI investigator to dispatch root-cause analysis via the host's `CLIAgentDispatch` HTTP API (`http://localhost:8032/v1/chat/completions`) with automatic CLI subprocess fallbacks, and build a full VitePress documentation suite in `monitorbot/docs/` with Mermaid diagram support.

**Architecture:** 
- In `app/investigator.py`, query `AI_DISPATCH_URL` (`http://localhost:8032/v1/chat/completions`) using OpenAI-compatible payload format. If connection fails or times out, fall back seamlessly to local `opencode` / `agy` CLI subprocess execution.
- Create `monitorbot/package.json` with VitePress and `vitepress-plugin-mermaid` to document architecture, event watching, SRE audits, notification fail-safe routing, and FastMCP tools.

**Tech Stack:** Python 3.12, FastAPI, Requests, Pytest, Node.js, VitePress 1.6+, Mermaid, vitepress-plugin-mermaid

## Global Constraints
- Do not remove the existing CLI subprocess fallback paths (`opencode run`, `agy --print`) — they provide essential resilience if the dispatch daemon is ever offline.
- When running tests, always run with `-m "not live"`: `pytest -m "not live"`.
- VitePress must build cleanly (`npm run docs:build`) with 0 broken links.
- Commit frequently with atomic commit messages following conventional commits (`feat:`, `fix:`, `docs:`).

---

### Task 1: Environment & Config Updates for AI Dispatch HTTP

**Files:**
- Modify: `monitorbot/.env:20-30`
- Modify: `monitorbot/app/investigator.py:20-40`
- Create: `monitorbot/tests/test_investigator_dispatch.py`

**Interfaces:**
- Produces: `call_ai_dispatch_server(prompt: str, model_id: str = None, timeout: int = None) -> tuple[str, float]` in `app/investigator.py` returning `(output_text, duration_seconds)`.

- [ ] **Step 1: Write the failing unit tests for `call_ai_dispatch_server`**

```python
# monitorbot/tests/test_investigator_dispatch.py
import pytest
from unittest.mock import patch, MagicMock
from app.investigator import call_ai_dispatch_server

def test_call_ai_dispatch_server_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [
            {"message": {"content": "{\"root_cause\": \"Test cause\", \"proposed_fix\": \"docker restart test\"}"}}
        ]
    }
    with patch("requests.post", return_value=mock_resp) as mock_post:
        output, duration = call_ai_dispatch_server("Test prompt", model_id="opencode", timeout=30)
        assert "Test cause" in output
        assert duration >= 0
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["model"] == "opencode"
        assert kwargs["json"]["messages"][0]["content"] == "Test prompt"

def test_call_ai_dispatch_server_http_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.raise_for_status.side_effect = Exception("Server Error")
    with patch("requests.post", return_value=mock_resp):
        with pytest.raises(Exception):
            call_ai_dispatch_server("Test prompt")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_investigator_dispatch.py -v`
Expected: FAIL with `ImportError: cannot import name 'call_ai_dispatch_server'`

- [ ] **Step 3: Implement `call_ai_dispatch_server` in `app/investigator.py` and update `.env`**

In `monitorbot/.env`:
```bash
AI_DISPATCH_URL=http://localhost:8032/v1
AI_MODEL=opencode
AI_DISPATCH_TIMEOUT=180
```

In `monitorbot/app/investigator.py`:
```python
import time

AI_DISPATCH_URL = os.getenv("AI_DISPATCH_URL", "http://localhost:8032/v1").rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", os.getenv("AI_EXECUTOR", "opencode")).lower()
AI_DISPATCH_TIMEOUT = int(os.getenv("AI_DISPATCH_TIMEOUT", "180"))

def call_ai_dispatch_server(prompt: str, model_id: str = None, timeout: int = None) -> tuple[str, float]:
    """Call CLIAgentDispatch OpenAI-compatible HTTP endpoint (:8032/v1/chat/completions)."""
    target_model = model_id or AI_MODEL
    req_timeout = timeout or AI_DISPATCH_TIMEOUT
    url = f"{AI_DISPATCH_URL}/chat/completions"
    
    payload = {
        "model": target_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    
    start_time = time.time()
    resp = requests.post(url, json=payload, timeout=req_timeout)
    duration = time.time() - start_time
    resp.raise_for_status()
    
    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        raise ValueError("No choices returned from AI dispatch gateway")
    
    content = choices[0].get("message", {}).get("content", "")
    return content, duration
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_investigator_dispatch.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git -C /containers add monitorbot/.env monitorbot/app/investigator.py monitorbot/tests/test_investigator_dispatch.py
git -C /containers commit -m "feat(investigator): add call_ai_dispatch_server for CLIAgentDispatch HTTP gateway"
```

---

### Task 2: Refactor Investigator Execution Flow with Resilient CLI Fallback

**Files:**
- Modify: `monitorbot/app/investigator.py:150-225`
- Modify: `monitorbot/tests/test_investigator_dispatch.py`

**Interfaces:**
- Consumes: `call_ai_dispatch_server`
- Produces: Resilient AI execution inside `run_investigation_logic` that prioritizes HTTP and falls back to CLI subprocess on failure.

- [ ] **Step 1: Write unit tests verifying fallback behavior**

In `monitorbot/tests/test_investigator_dispatch.py`:
```python
def test_investigation_fallback_to_cli_when_http_fails(db_session):
    from app.database import Incident, Target
    from app.investigator import run_investigation_logic

    target = Target(id="test-fb-target", type="docker")
    db_session.add(target)
    inc = Incident(
        id="test-fb-uuid",
        target_id="test-fb-target",
        status="DETECTED",
        error_logs="Fatal error"
    )
    db_session.add(inc)
    db_session.commit()

    # Mock HTTP failure, CLI success
    with patch("app.investigator.call_ai_dispatch_server", side_effect=Exception("HTTP connection refused")), \
         patch("subprocess.run") as mock_subproc, \
         patch("app.notifier.send_incident_notification"):
        
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = '{"root_cause": "CLI fallback cause", "proposed_fix": "docker restart test", "category": "crash"}'
        mock_subproc.return_value = mock_res

        run_investigation_logic(db_session, inc)

        assert inc.status == "PENDING_USER"
        assert inc.root_cause == "CLI fallback cause"
        mock_subproc.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails before implementation**

Run: `pytest tests/test_investigator_dispatch.py -k "test_investigation_fallback_to_cli_when_http_fails"`
Expected: FAIL

- [ ] **Step 3: Update `run_investigation_logic` in `app/investigator.py`**

Refactor Step 4 of `run_investigation_logic`:
```python
    # 4. Run AI executor via CLIAgentDispatch HTTP with local CLI subprocess fallback
    output = None
    exec_duration = 0.0
    current_executor = AI_MODEL
    dispatch_success = False

    try:
        logger.info(f"Dispatching investigation prompt to CLIAgentDispatch HTTP ({AI_DISPATCH_URL}) with model '{current_executor}'...")
        output, exec_duration = call_ai_dispatch_server(prompt, model_id=current_executor)
        dispatch_success = True
    except Exception as dispatch_err:
        logger.warning(f"CLIAgentDispatch HTTP failed ({dispatch_err}). Falling back to direct CLI subprocess execution...")
        
        start_time = time.time()
        if "opencode" in current_executor:
            cmd = [OPENCODE_PATH, "run", "--auto", "--model", f"{OPENCODE_PROVIDER_ID}/{OPENCODE_MODEL_ID}", prompt]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                exec_duration = time.time() - start_time
                if result.returncode == 0:
                    output = result.stdout
                else:
                    logger.error(f"opencode CLI execution failed: {result.stderr}")
                    incident.status = "FAILED"
                    incident.execution_log = f"opencode CLI error: {result.stderr}"
                    db.commit()
                    log_transcript_event(incident_id, "AI_EXECUTION_FAILED", {"error": result.stderr})
                    return
            except Exception as cli_err:
                logger.error(f"opencode CLI error: {cli_err}")
                incident.status = "FAILED"
                incident.execution_log = f"opencode error: {cli_err}"
                db.commit()
                log_transcript_event(incident_id, "AI_EXECUTION_FAILED", {"error": str(cli_err)})
                return
        else:
            cmd = [AGY_PATH, "--model", AGY_MODEL, "--dangerously-skip-permissions", "--print", prompt]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                exec_duration = time.time() - start_time
                if result.returncode != 0:
                    logger.error(f"agy execution failed: {result.stderr}")
                    incident.status = "FAILED"
                    incident.execution_log = f"agy error: {result.stderr}"
                    db.commit()
                    log_transcript_event(incident_id, "AI_EXECUTION_FAILED", {"error": result.stderr})
                    return
                output = result.stdout
            except Exception as agy_err:
                logger.error(f"agy execution error: {agy_err}")
                incident.status = "FAILED"
                incident.execution_log = f"agy error: {agy_err}"
                db.commit()
                log_transcript_event(incident_id, "AI_EXECUTION_FAILED", {"error": str(agy_err)})
                return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_investigator_dispatch.py -v`
Expected: PASS (all 3 tests pass)

- [ ] **Step 5: Run full test suite regression**

Run: `pytest -m "not live"`
Expected: 222 passed (0 failed)

- [ ] **Step 6: Commit**

```bash
git -C /containers add monitorbot/app/investigator.py monitorbot/tests/test_investigator_dispatch.py
git -C /containers commit -m "feat(investigator): route investigation prompts via CLIAgentDispatch HTTP with CLI fallback"
```

---

### Task 3: Root VitePress Scaffolding & Configuration

**Files:**
- Create: `monitorbot/package.json`
- Create: `monitorbot/docs/.vitepress/config.mts`

- [ ] **Step 1: Create `monitorbot/package.json`**

```json
{
  "name": "monitorbot-docs",
  "version": "2.2.1",
  "private": true,
  "scripts": {
    "docs:dev": "vitepress dev docs",
    "docs:build": "vitepress build docs",
    "docs:preview": "vitepress preview docs"
  },
  "devDependencies": {
    "vitepress": "^1.6.4",
    "mermaid": "^11.4.1",
    "vitepress-plugin-mermaid": "^2.0.17"
  }
}
```

- [ ] **Step 2: Run npm install**

Run: `cd /containers/monitorbot && npm install`
Expected: Success, node_modules created.

- [ ] **Step 3: Create `monitorbot/docs/.vitepress/config.mts`**

Configure title, description, markdown mermaid plugin, navigation bar, and comprehensive sidebar matching the documentation structure.

- [ ] **Step 4: Verify VitePress config load**

Run: `npx vitepress --version`
Expected: Outputs VitePress version (1.6.x).

- [ ] **Step 5: Commit scaffolding**

```bash
git -C /containers add monitorbot/package.json monitorbot/package-lock.json monitorbot/docs/.vitepress/config.mts
git -C /containers commit -m "build(docs): scaffold VitePress documentation system with mermaid plugin"
```

---

### Task 4: Write Core Architecture & SRE Documentation Pages

**Files:**
- Create: `monitorbot/docs/index.md`
- Create: `monitorbot/docs/architecture/overview.md`
- Create: `monitorbot/docs/architecture/event-watcher.md`
- Create: `monitorbot/docs/architecture/sre-auditor.md`

- [ ] **Step 1: Create `index.md` (Landing Page)**
Features hero title, tagline, action buttons, key feature cards (Autonomous SRE, Multi-Agent Delegation, Fail-Safe Notifications, FUSE Mount Auditor).

- [ ] **Step 2: Create `architecture/overview.md`**
System topology diagram (Mermaid), host/runtime context, database schema overview, background worker lifecycle.

- [ ] **Step 3: Create `architecture/event-watcher.md`**
Docker socket listener, debouncing, intelligent noise suppression, graceful SIGTERM handling, circuit breaker trip thresholds.

- [ ] **Step 4: Create `architecture/sre-auditor.md`**
Scheduled container log analysis, error burst detection, per-container incident granularity, canary stack audit phases.

- [ ] **Step 5: Commit**

```bash
git -C /containers add monitorbot/docs/index.md monitorbot/docs/architecture/
git -C /containers commit -m "docs: add core architecture, event watcher, and SRE auditor documentation"
```

---

### Task 5: Write AI Agent Dispatch & Notification Fail-Safe Documentation Pages

**Files:**
- Create: `monitorbot/docs/ai/agent-dispatch.md`
- Create: `monitorbot/docs/ai/memory-rag.md`
- Create: `monitorbot/docs/ai/prompt-contract.md`
- Create: `monitorbot/docs/reliability/notifications.md`
- Create: `monitorbot/docs/reliability/storage-auditor.md`
- Create: `monitorbot/docs/reliability/circuit-breakers.md`
- Create: `monitorbot/docs/reference/api.md`
- Create: `monitorbot/docs/reference/mcp.md`
- Create: `monitorbot/docs/reference/configuration.md`

- [ ] **Step 1: Create AI docs (`agent-dispatch.md`, `memory-rag.md`, `prompt-contract.md`)**
Document CLIAgentDispatch HTTP integration, fallback flow, OpenCode & Antigravity execution, Qdrant vector memory, JSON remediation contract.

- [ ] **Step 2: Create Reliability docs (`notifications.md`, `storage-auditor.md`, `circuit-breakers.md`)**
Document ntfy action buttons format, LAN IP rewriting (`LOCAL_WEBHOOK_BASE_URL`), SMTP fallback, proactive FUSE/mount health auditing.

- [ ] **Step 3: Create Reference docs (`api.md`, `mcp.md`, `configuration.md`)**
REST API routes (`/api/incidents`, `/api/stacks`, `/api/upgrades`), FastMCP SSE endpoints (`/sse`, `/mcp/sse`), and environment variables.

- [ ] **Step 4: Test build VitePress site**

Run: `cd /containers/monitorbot && npm run docs:build`
Expected: Clean build, 0 dead links.

- [ ] **Step 5: Commit**

```bash
git -C /containers add monitorbot/docs/ai/ monitorbot/docs/reliability/ monitorbot/docs/reference/
git -C /containers commit -m "docs: add AI delegation, reliability, and API reference documentation"
```

---

### Task 6: Final Verification, Service Restart & Remote Push

**Files:**
- All modified files

- [ ] **Step 1: Run full test suite**

Run: `pytest -m "not live"`
Expected: All tests pass cleanly.

- [ ] **Step 2: Restart `monitorbot.service` and verify status**

Run: `sudo systemctl restart monitorbot && sudo systemctl status monitorbot --no-pager`
Expected: Active (running).

- [ ] **Step 3: Push to both remotes**

```bash
git -C /containers push origin main
git -C /containers subtree split --prefix=monitorbot -b monitorbot-split
git -C /containers push monitorbot-origin monitorbot-split:main
git -C /containers branch -D monitorbot-split
```
Expected: Both remotes up to date.
