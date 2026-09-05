import pytest
from unittest.mock import patch, MagicMock
from app.stack_watcher import is_benign_noise, BENIGN_FILTER_PATTERNS
from app.watcher import run_watcher

def test_recyclarr_legend_filtered():
    line = "Legend: ✓ ok · ~ partial · ✗ failed · -- skipped"
    assert is_benign_noise(line) is True

def test_tinyauth_401_probe_filtered():
    line = "2026-08-30T08:00:10Z WRN Client Error address=172.31.0.58:50964 status=401"
    assert is_benign_noise(line) is True

def test_wud_local_image_tag_filtered():
    line = "08:00:01.000  WARN whats-up-docker/watcher.docker.fast: Cannot get a reliable tag for this image [sha256:f1234abc]"
    assert is_benign_noise(line) is True

def test_huggingface_unauthenticated_notice_filtered():
    line = "Warning: You are sending unauthenticated requests to the HF Hub"
    assert is_benign_noise(line) is True

def test_plextraktsync_transient_timeout_filtered():
    line = "ERROR    HTTPSConnectionPool(host='172-20-0-1.plex.direct', port=32400): Read timed out."
    assert is_benign_noise(line) is True

def test_real_errors_not_filtered():
    line = "ERROR: Failed to connect to postgres database on port 5432: connection refused"
    assert is_benign_noise(line) is False

def test_watcher_graceful_exit_codes_ignored():
    """Test that exit codes 0, 143 (SIGTERM), and 130 (SIGINT) do not trigger failure processing."""
    graceful_events = [
        {"Action": "die", "id": "c1", "Actor": {"Attributes": {"name": "app1", "exitCode": "0", "com.docker.compose.project": "media"}}},
        {"Action": "die", "id": "c2", "Actor": {"Attributes": {"name": "app2", "exitCode": "143", "com.docker.compose.project": "media"}}},
        {"Action": "die", "id": "c3", "Actor": {"Attributes": {"name": "app3", "exitCode": "130", "com.docker.compose.project": "media"}}},
    ]
    crash_events = [
        {"Action": "die", "id": "c4", "Actor": {"Attributes": {"name": "app4", "exitCode": "1", "com.docker.compose.project": "media"}}},
        {"Action": "die", "id": "c5", "Actor": {"Attributes": {"name": "app5", "exitCode": "137", "com.docker.compose.project": "media"}}},
    ]

    mock_client = MagicMock()
    mock_client.events.side_effect = [graceful_events + crash_events, Exception("StopLoop")]

    class StopLoopException(Exception):
        pass

    with patch("docker.from_env", return_value=mock_client), \
         patch("app.watcher.process_failure") as mock_process, \
         patch("time.sleep", side_effect=StopLoopException):
        try:
            run_watcher()
        except StopLoopException:
            pass

        # Only crash events (app4, app5) should have triggered process_failure
        assert mock_process.call_count == 2
        calls = [call[0] for call in mock_process.call_args_list]
        called_names = [c[1] for c in calls]
        assert "app1" not in called_names
        assert "app2" not in called_names
        assert "app3" not in called_names
        assert "app4" in called_names
        assert "app5" in called_names
