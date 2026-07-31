"""
tests/test_live_executors.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Live end-to-end integration test suite for AI Executors:
  1. OpenCode Serve HTTP API (localhost:8447)
  2. OpenCode CLI Subprocess (opencode run)
  3. AGY CLI Subprocess (agy)

Run explicitly via:
  pytest /containers/monitorbot/tests/test_live_executors.py -v -s
"""

import os
import subprocess
import requests
import pytest
from app.investigator import (
    call_opencode_server,
    OPENCODE_PATH,
    AGY_PATH,
    OPENCODE_SERVER_URL,
    OPENCODE_PROVIDER_ID,
    OPENCODE_MODEL_ID
)

@pytest.mark.live
def test_live_opencode_serve_http_api():
    """Verify live HTTP API interaction with opencode serve daemon."""
    prompt = "Respond with exactly: LIVE_SERVE_VERIFIED"
    res = call_opencode_server(prompt, timeout=60)
    assert "LIVE_SERVE_VERIFIED" in res


@pytest.mark.live
def test_live_opencode_cli_subprocess():
    """Verify live CLI subprocess invocation of opencode run."""
    model_arg = f"{OPENCODE_PROVIDER_ID}/{OPENCODE_MODEL_ID}"
    prompt = "Respond with exactly: LIVE_OPENCODE_CLI_VERIFIED"
    cmd = [OPENCODE_PATH, "run", "--auto", "--model", model_arg, prompt]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"opencode CLI error: {result.stderr}"
    assert "LIVE_OPENCODE_CLI_VERIFIED" in result.stdout


@pytest.mark.live
def test_live_agy_cli_subprocess():
    """Verify live CLI subprocess invocation of agy."""
    prompt = "Respond with exactly: LIVE_AGY_CLI_VERIFIED"
    cmd = [AGY_PATH, "--model", "gemini-3.5-flash-medium", "--dangerously-skip-permissions", "--print", prompt]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"agy CLI error: {result.stderr}"
    assert "LIVE_AGY_CLI_VERIFIED" in result.stdout
