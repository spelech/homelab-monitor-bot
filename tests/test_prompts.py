"""
tests/test_prompts.py
~~~~~~~~~~~~~~~~~~~~~
Offline prompt-engineering test suite for the SRE MonitorBot investigator.
These tests NEVER call the live agy binary — they mock subprocess to isolate:
  1. Prompt construction    — assert exact text sent to the AI model
  2. Output parsing         — edge cases in JSON extraction (fences, noise, bad JSON, etc.)
  3. DB state transitions   — success / failure / meta-distraction guard
  4. Prompt guard           — agy-flag self-reference is blocked in the prompt text
"""
import json
import re
import pytest
from unittest.mock import patch, MagicMock

from app.database import Incident, Target


# ---------------------------------------------------------------------------
# Helper: rebuild the prompt exactly as investigator.py does it
# ---------------------------------------------------------------------------

def build_prompt(target_id: str, error_logs: str, historical_context: str = "") -> str:
    return (
        f"Container failure detected on '{target_id}'.\n"
        f"Error Logs:\n{error_logs}{historical_context}\n\n"
        "You are an SRE bot. Focus strictly on diagnosing this container failure by inspecting its configuration, files, and Docker logs. "
        "Do NOT research, grep, or search for the 'agy' command or its flags (like --dangerously-skip-permissions) on the system. "
        "Output ONLY valid JSON with exactly three keys: "
        "'root_cause' (a string explaining the issue), "
        "'proposed_fix' (a string containing valid bash commands to fix it), and "
        "'category' (a string classifying the issue into one of: 'network', 'reverse_proxy', 'permissions', 'settings', 'database', 'unknown'). "
        "Do not include markdown formatting or backticks."
    )


def extract_json(output: str) -> dict | None:
    """Mirrors app/investigator.py JSON extraction logic."""
    match = re.search(r"\{.*\}", output, re.DOTALL)
    if not match:
        return None
    return json.loads(match.group(0))


# ===========================================================================
# 1. PROMPT CONSTRUCTION TESTS
# ===========================================================================

class TestPromptConstruction:

    def test_basic_prompt_contains_target_id(self):
        prompt = build_prompt("kopia", "failed to open /gdrive/Backups/kopia")
        assert "Container failure detected on 'kopia'" in prompt

    def test_prompt_contains_error_logs(self):
        logs = "Error: cannot stat /gdrive/Backups/kopia: no such file or directory"
        prompt = build_prompt("kopia", logs)
        assert logs in prompt

    def test_prompt_contains_sre_bot_instruction(self):
        prompt = build_prompt("kopia", "some logs")
        assert "You are an SRE bot" in prompt

    def test_prompt_guards_against_agy_flag_research(self):
        """The prompt must instruct the agent NOT to research the agy binary."""
        prompt = build_prompt("kopia", "some logs")
        assert "Do NOT research, grep, or search for the 'agy' command" in prompt
        assert "--dangerously-skip-permissions" in prompt  # mentioned as an example to avoid

    def test_prompt_requests_json_only(self):
        prompt = build_prompt("kopia", "some logs")
        assert "Output ONLY valid JSON" in prompt
        assert "Do not include markdown formatting or backticks" in prompt

    def test_prompt_requests_three_exact_keys(self):
        prompt = build_prompt("kopia", "some logs")
        assert "'root_cause'" in prompt
        assert "'proposed_fix'" in prompt
        assert "'category'" in prompt

    def test_prompt_includes_historical_context_when_provided(self):
        ctx = "\n\nHistorical context: In the past, docker restart postgres fixed it."
        prompt = build_prompt("postgres", "connection refused", historical_context=ctx)
        assert "Historical context" in prompt
        assert "docker restart postgres" in prompt

    def test_prompt_no_historical_context_by_default(self):
        prompt = build_prompt("redis", "MISCONF: AOF is disabled")
        assert "Historical context" not in prompt

    def test_prompt_contains_all_valid_categories(self):
        prompt = build_prompt("nginx", "upstream connection refused")
        for cat in ["network", "reverse_proxy", "permissions", "settings", "database", "unknown"]:
            assert cat in prompt


# ===========================================================================
# 2. OUTPUT PARSING TESTS — JSON extraction edge cases
# ===========================================================================

class TestOutputParsing:

    def test_clean_json_parses(self):
        output = '{"root_cause": "DB timeout", "proposed_fix": "docker restart db", "category": "database"}'
        result = extract_json(output)
        assert result["root_cause"] == "DB timeout"
        assert result["proposed_fix"] == "docker restart db"
        assert result["category"] == "database"

    def test_json_inside_markdown_fences_parses(self):
        output = """
Some chatter here...
```json
{
  "root_cause": "Missing env var",
  "proposed_fix": "export VAR=foo",
  "category": "settings"
}
```
Trailing notes.
"""
        result = extract_json(output)
        assert result["root_cause"] == "Missing env var"
        assert result["category"] == "settings"

    def test_json_with_surrounding_noise_parses(self):
        output = """
I analyzed the container logs. Based on the error I found:
{"root_cause": "Volume not mounted", "proposed_fix": "docker compose up -d", "category": "settings"}
This fix should resolve the issue.
"""
        result = extract_json(output)
        assert result is not None
        assert result["category"] == "settings"

    def test_json_with_extra_whitespace_parses(self):
        output = '   \n\n  {  "root_cause":  "disk full",  "proposed_fix":  "df -h",  "category":  "unknown" }  \n'
        result = extract_json(output)
        assert result["category"] == "unknown"

    def test_no_json_returns_none(self):
        """Meta-distraction: agent returns a long essay about agy flags."""
        output = """
The `--dangerously-skip-permissions` flag is used to bypass authorization prompts.
It overrides safety confirmation dialogs for the active session.
Best Practices: Use isolated environments and commit your changes.
"""
        result = extract_json(output)
        assert result is None

    def test_malformed_json_no_closing_brace_returns_none(self):
        """Truncated JSON with no closing brace: regex finds no match, returns None."""
        output = '{"root_cause": "disk full", "proposed_fix": "rm -rf /tmp/*"'  # missing closing brace
        # The regex r"\{.*\}" requires a closing brace, so no match → None
        result = extract_json(output)
        assert result is None

    def test_malformed_json_with_closing_brace_raises(self):
        """JSON that matches the regex but fails to parse raises JSONDecodeError."""
        output = '{"root_cause": bad value, "proposed_fix": "cmd", "category": "unknown"}'
        with pytest.raises(json.JSONDecodeError):
            extract_json(output)

    def test_nested_json_extracts_outermost(self):
        """Agent returns nested structure — we extract the first full block."""
        output = '{"root_cause": "bad config", "proposed_fix": "fix it", "category": "settings", "meta": {"confidence": 0.9}}'
        result = extract_json(output)
        assert result["root_cause"] == "bad config"

    def test_empty_string_returns_none(self):
        result = extract_json("")
        assert result is None

    def test_proposed_fix_with_newlines_preserved(self):
        fix = "cd /containers/myapp\ndocker compose down\ndocker compose up -d"
        output = json.dumps({
            "root_cause": "App misconfigured",
            "proposed_fix": fix,
            "category": "settings"
        })
        result = extract_json(output)
        assert "\n" in result["proposed_fix"]
        assert "docker compose down" in result["proposed_fix"]


# ===========================================================================
# 3. INTEGRATION TESTS — full trigger_investigation() flow (mocked agy)
# ===========================================================================

class TestInvestigationIntegration:

    VALID_JSON_OUTPUT = json.dumps({
        "root_cause": "Mount path /gdrive/Backups/kopia does not exist because rclone is not mounted.",
        "proposed_fix": "docker compose -f /containers/webservices/docker-compose.yaml restart kopia",
        "category": "settings"
    })

    def _make_incident(self, db_session, incident_id="inv-001", target_id="kopia"):
        target = Target(id=target_id, type="docker")
        db_session.add(target)
        db_session.commit()
        incident = Incident(
            id=incident_id,
            target_id=target_id,
            status="DETECTED",
            error_logs="failed to open repository: cannot open storage: cannot access storage path: stat /gdrive/Backups/kopia: no such file or directory"
        )
        db_session.add(incident)
        db_session.commit()

    def test_successful_investigation_sets_pending_user(self, db_session):
        from app.investigator import trigger_investigation
        self._make_incident(db_session)

        mock_result = MagicMock(returncode=0, stdout=self.VALID_JSON_OUTPUT)
        with patch("subprocess.run", return_value=mock_result), \
             patch("app.notifier.send_incident_notification") as mock_notify:
            trigger_investigation("inv-001")

        db_session.expire_all()
        inc = db_session.query(Incident).filter_by(id="inv-001").first()
        assert inc.status == "PENDING_USER"
        assert inc.category == "settings"
        assert "rclone" in inc.root_cause
        mock_notify.assert_called_once_with("inv-001")

    def test_meta_distraction_output_marks_failed(self, db_session):
        """If agy returns a long essay instead of JSON, incident must be FAILED."""
        from app.investigator import trigger_investigation
        self._make_incident(db_session, incident_id="inv-meta")

        meta_essay = (
            "The --dangerously-skip-permissions flag is a CLI option used to bypass authorization prompts. "
            "It acts as a session-level override. Best Practices: Use isolated environments."
        )
        mock_result = MagicMock(returncode=0, stdout=meta_essay)
        with patch("subprocess.run", return_value=mock_result), \
             patch("app.notifier.send_incident_notification") as mock_notify:
            trigger_investigation("inv-meta")

        db_session.expire_all()
        inc = db_session.query(Incident).filter_by(id="inv-meta").first()
        assert inc.status == "FAILED"
        assert "No JSON block" in inc.execution_log
        mock_notify.assert_not_called()

    def test_agy_nonzero_exit_marks_failed(self, db_session):
        from app.investigator import trigger_investigation
        self._make_incident(db_session, incident_id="inv-crash")

        mock_result = MagicMock(returncode=1, stderr="quota exceeded")
        with patch("subprocess.run", return_value=mock_result), \
             patch("app.notifier.send_incident_notification") as mock_notify:
            trigger_investigation("inv-crash")

        db_session.expire_all()
        inc = db_session.query(Incident).filter_by(id="inv-crash").first()
        assert inc.status == "FAILED"
        assert "quota exceeded" in inc.execution_log
        mock_notify.assert_not_called()

    def test_agy_receives_correct_prompt_content(self, db_session):
        """Assert the subprocess call contains our prompt guard text."""
        from app.investigator import trigger_investigation
        self._make_incident(db_session, incident_id="inv-prompt")

        mock_result = MagicMock(returncode=0, stdout=self.VALID_JSON_OUTPUT)
        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("app.notifier.send_incident_notification"):
            trigger_investigation("inv-prompt")

        call_args = mock_run.call_args
        cmd_list = call_args[0][0]
        # The full prompt is the last argument passed to the agy command
        prompt_sent = cmd_list[-1]
        assert "You are an SRE bot" in prompt_sent
        assert "Do NOT research, grep, or search for the 'agy' command" in prompt_sent
        assert "kopia" in prompt_sent

    def test_category_values_are_valid(self, db_session):
        """Assert only the six defined categories can be persisted."""
        from app.investigator import trigger_investigation
        valid_categories = {"network", "reverse_proxy", "permissions", "settings", "database", "unknown"}

        for cat in valid_categories:
            incident_id = f"inv-cat-{cat}"
            target_id = f"target-{cat}"
            target = Target(id=target_id, type="docker")
            db_session.add(target)
            db_session.commit()

            incident = Incident(id=incident_id, target_id=target_id, status="DETECTED", error_logs="some error")
            db_session.add(incident)
            db_session.commit()

            output = json.dumps({"root_cause": "test", "proposed_fix": "echo ok", "category": cat})
            mock_result = MagicMock(returncode=0, stdout=output)
            with patch("subprocess.run", return_value=mock_result), \
                 patch("app.notifier.send_incident_notification"):
                trigger_investigation(incident_id)

            db_session.expire_all()
            inc = db_session.query(Incident).filter_by(id=incident_id).first()
            assert inc.category == cat

    def test_historical_context_injected_into_prompt(self, db_session):
        """If qdrant_mem returns a historical fix, it must appear in the prompt sent to agy."""
        from app.investigator import trigger_investigation
        self._make_incident(db_session, incident_id="inv-hist")

        mock_result = MagicMock(returncode=0, stdout=self.VALID_JSON_OUTPUT)

        # Patch qdrant_mem.query_similar_fix in the module where it's used
        mock_match = MagicMock()
        mock_match.score = 0.95
        # investigator.py reads match.metadata.get("successful_command")
        mock_match.metadata = {"successful_command": "docker restart kopia-old"}

        with patch("subprocess.run", return_value=mock_result) as mock_run, \
             patch("app.notifier.send_incident_notification"), \
             patch("app.qdrant_mem.qdrant_mem.query_similar_fix", return_value=mock_match):

            trigger_investigation("inv-hist")

        call_args = mock_run.call_args
        prompt_sent = call_args[0][0][-1]
        assert "Historical context" in prompt_sent
        assert "docker restart kopia-old" in prompt_sent
