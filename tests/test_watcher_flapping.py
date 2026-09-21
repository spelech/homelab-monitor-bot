import time
import pytest
from unittest.mock import patch, MagicMock
from app.watcher import (
    CrashTracker,
    is_container_crash_looping,
    is_container_healthy,
    run_watcher,
)

def test_single_clean_restart_is_not_crash_loop():
    tracker = CrashTracker()
    assert tracker.record_and_check_crash_loop("matter-hub", "1") is False

def test_repeated_crash_is_crash_loop():
    tracker = CrashTracker()
    tracker.record_and_check_crash_loop("matter-hub", "1")
    assert tracker.record_and_check_crash_loop("matter-hub", "1") is True

def test_graceful_exits_ignored():
    tracker = CrashTracker()
    # Code 0 (clean exit)
    assert tracker.record_and_check_crash_loop("app-service", "0") is False
    assert tracker.get_crash_count("app-service") == 0

    # Code 143 (SIGTERM graceful stop)
    assert tracker.record_and_check_crash_loop("app-service", "143") is False
    assert tracker.get_crash_count("app-service") == 0

    # Code 130 (SIGINT graceful stop)
    assert tracker.record_and_check_crash_loop("app-service", "130") is False
    assert tracker.get_crash_count("app-service") == 0

    # Integer inputs
    assert tracker.record_and_check_crash_loop("app-service", 0) is False
    assert tracker.record_and_check_crash_loop("app-service", 143) is False
    assert tracker.record_and_check_crash_loop("app-service", 130) is False
    assert tracker.get_crash_count("app-service") == 0

def test_crashes_expire_after_window():
    tracker = CrashTracker(window_seconds=300)
    base_time = 1000.0

    # First crash at base_time
    assert tracker.record_and_check_crash_loop("app-service", "1", now=base_time) is False
    assert tracker.get_crash_count("app-service", now=base_time) == 1

    # Second crash 301 seconds later (window expired)
    assert tracker.record_and_check_crash_loop("app-service", "1", now=base_time + 301) is False
    assert tracker.get_crash_count("app-service", now=base_time + 301) == 1

    # Third crash within 5 minutes of second crash
    assert tracker.record_and_check_crash_loop("app-service", "1", now=base_time + 350) is True
    assert tracker.get_crash_count("app-service", now=base_time + 350) == 2

def test_independent_containers():
    tracker = CrashTracker()
    assert tracker.record_and_check_crash_loop("container-a", "1") is False
    assert tracker.record_and_check_crash_loop("container-b", "1") is False

    # Second crash for container-a should loop, but container-b still only has 1
    assert tracker.record_and_check_crash_loop("container-a", "1") is True
    assert tracker.get_crash_count("container-b") == 1

def test_is_container_crash_looping_module_helper():
    with patch("app.watcher.crash_tracker") as mock_tracker:
        mock_tracker.record_and_check_crash_loop.return_value = True
        res = is_container_crash_looping("my-app", "1")
        assert res is True
        mock_tracker.record_and_check_crash_loop.assert_called_once_with("my-app", "1")

def test_is_container_healthy_checks():
    mock_client = MagicMock()
    mock_container = MagicMock()
    mock_client.containers.get.return_value = mock_container

    # Healthy running container with no explicit healthcheck
    mock_container.attrs = {"State": {"Running": True, "Health": {"Status": "none"}}}
    assert is_container_healthy(mock_client, "app") is True

    # Healthy running container with healthy status
    mock_container.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
    assert is_container_healthy(mock_client, "app") is True

    # Stopped container
    mock_container.attrs = {"State": {"Running": False, "Health": {"Status": "none"}}}
    assert is_container_healthy(mock_client, "app") is False

    # Running container with unhealthy status
    mock_container.attrs = {"State": {"Running": True, "Health": {"Status": "unhealthy"}}}
    assert is_container_healthy(mock_client, "app") is False

    # Container lookup throws exception (e.g. NotFound)
    mock_client.containers.get.side_effect = Exception("Container not found")
    assert is_container_healthy(mock_client, "app") is False

def test_watcher_transient_restart_auto_recovered():
    mock_events = [
        {
            "Action": "die",
            "Actor": {
                "Attributes": {
                    "name": "media-app",
                    "exitCode": "1",
                    "com.docker.compose.project": "media",
                }
            },
            "id": "media-app-id",
        }
    ]
    mock_client = MagicMock()
    mock_client.events.side_effect = [mock_events, KeyboardInterrupt("Stop")]

    with patch("docker.from_env", return_value=mock_client), \
         patch("app.watcher.time.sleep") as mock_sleep, \
         patch("app.watcher.is_container_healthy", return_value=True) as mock_healthy, \
         patch("app.watcher.process_failure") as mock_proc, \
         patch("app.watcher.crash_tracker") as mock_tracker:

        mock_tracker.record_and_check_crash_loop.return_value = False

        try:
            run_watcher()
        except KeyboardInterrupt:
            pass

        # Should wait 3s for Docker restart policy
        mock_sleep.assert_called_with(3)
        # Should check health
        mock_healthy.assert_called_once_with(mock_client, "media-app")
        # Should NOT trigger process_failure
        mock_proc.assert_not_called()

def test_watcher_first_crash_fails_to_recover_creates_incident():
    mock_events = [
        {
            "Action": "die",
            "Actor": {
                "Attributes": {
                    "name": "failing-app",
                    "exitCode": "1",
                    "com.docker.compose.project": "media",
                }
            },
            "id": "failing-app-id",
        }
    ]
    mock_client = MagicMock()
    mock_client.events.side_effect = [mock_events, KeyboardInterrupt("Stop")]

    with patch("docker.from_env", return_value=mock_client), \
         patch("app.watcher.time.sleep") as mock_sleep, \
         patch("app.watcher.is_container_healthy", return_value=False) as mock_healthy, \
         patch("app.watcher.process_failure") as mock_proc, \
         patch("app.watcher.crash_tracker") as mock_tracker:

        mock_tracker.record_and_check_crash_loop.return_value = False

        try:
            run_watcher()
        except KeyboardInterrupt:
            pass

        mock_sleep.assert_called_with(3)
        mock_healthy.assert_called_once_with(mock_client, "failing-app")
        # Failed to recover after 3s -> triggers process_failure
        mock_proc.assert_called_once()
        assert "failed to recover after 3s" in mock_proc.call_args[0][3]

def test_watcher_crash_loop_triggers_process_failure_immediately():
    mock_events = [
        {
            "Action": "die",
            "Actor": {
                "Attributes": {
                    "name": "looping-app",
                    "exitCode": "1",
                    "com.docker.compose.project": "media",
                }
            },
            "id": "looping-app-id",
        }
    ]
    mock_client = MagicMock()
    mock_client.events.side_effect = [mock_events, KeyboardInterrupt("Stop")]

    with patch("docker.from_env", return_value=mock_client), \
         patch("app.watcher.time.sleep") as mock_sleep, \
         patch("app.watcher.process_failure") as mock_proc, \
         patch("app.watcher.crash_tracker") as mock_tracker:

        # Simulating crash loop detected
        mock_tracker.record_and_check_crash_loop.return_value = True

        try:
            run_watcher()
        except KeyboardInterrupt:
            pass

        # Should NOT sleep to wait for recovery, triggers failure immediately
        mock_sleep.assert_not_called()
        mock_proc.assert_called_once()
        assert "crash-loop" in mock_proc.call_args[0][3].lower()
