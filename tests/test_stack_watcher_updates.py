import time
from unittest.mock import MagicMock, patch
import pytest
from app.stack_watcher import StackWatcherManager, parse_image_reference


def test_parse_image_reference():
    # Official library image
    ref1 = parse_image_reference("caddy:latest")
    assert ref1["registry"] == "registry-1.docker.io"
    assert ref1["repository"] == "library/caddy"
    assert ref1["tag"] == "latest"

    # User image on Docker Hub
    ref2 = parse_image_reference("koenkk/zigbee2mqtt:1.35.0")
    assert ref2["registry"] == "registry-1.docker.io"
    assert ref2["repository"] == "koenkk/zigbee2mqtt"
    assert ref2["tag"] == "1.35.0"

    # GHCR image
    ref3 = parse_image_reference("ghcr.io/home-assistant/home-assistant:stable")
    assert ref3["registry"] == "ghcr.io"
    assert ref3["repository"] == "home-assistant/home-assistant"
    assert ref3["tag"] == "stable"

    # Quay image
    ref4 = parse_image_reference("quay.io/coreos/etcd:v3.5.0")
    assert ref4["registry"] == "quay.io"
    assert ref4["repository"] == "coreos/etcd"
    assert ref4["tag"] == "v3.5.0"

    # Local / invalid / empty
    ref5 = parse_image_reference("")
    assert ref5["registry"] == ""
    assert ref5["repository"] == ""


def test_check_container_update_available():
    manager = StackWatcherManager()
    manager._update_cache.clear()

    # Remote returns a different digest
    with patch("requests.get") as mock_get, patch("requests.head") as mock_head:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"token": "mock_token"}
        mock_head.return_value.status_code = 200
        mock_head.return_value.headers = {"docker-content-digest": "sha256:new_remote_digest"}

        res = manager.check_container_update("caddy:latest", ["caddy@sha256:old_local_digest"])
        assert res["status"] == "UPDATE_AVAILABLE"
        assert res["update_available"] is True
        assert res["remote_digest"] == "sha256:new_remote_digest"
        assert res["local_digest"] == "sha256:old_local_digest"


def test_check_container_up_to_date_and_cached():
    manager = StackWatcherManager()
    manager._update_cache.clear()

    with patch("requests.get") as mock_get, patch("requests.head") as mock_head:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"token": "mock_token"}
        mock_head.return_value.status_code = 200
        mock_head.return_value.headers = {"docker-content-digest": "sha256:same_digest"}

        res = manager.check_container_update("caddy:latest", ["caddy@sha256:same_digest"])
        assert res["status"] == "UP_TO_DATE"
        assert res["update_available"] is False

        # Call again: verify cache is used and no network requests made
        mock_head.reset_mock()
        mock_get.reset_mock()
        cached_res = manager.check_container_update("caddy:latest", ["caddy@sha256:same_digest"])
        assert cached_res["status"] == "UP_TO_DATE"
        assert cached_res["update_available"] is False
        mock_head.assert_not_called()
        mock_get.assert_not_called()


def test_check_container_local_or_empty_image():
    manager = StackWatcherManager()
    manager._update_cache.clear()

    res = manager.check_container_update("", [])
    assert res["status"] == "LOCAL_IMAGE"
    assert res["update_available"] is False

    res_none = manager.check_container_update("<none>:<none>", [])
    assert res_none["status"] == "LOCAL_IMAGE"
    assert res_none["update_available"] is False


def test_check_container_registry_error_handles_gracefully():
    manager = StackWatcherManager()
    manager._update_cache.clear()

    with patch("requests.get", side_effect=Exception("Connection timeout")):
        res = manager.check_container_update("caddy:latest", ["caddy@sha256:some_digest"])
        assert res["status"] == "UNKNOWN"
        assert res["update_available"] is False
        assert "error" in res


def test_cache_ttl_expiration():
    manager = StackWatcherManager()
    manager._update_cache.clear()

    with patch("requests.get") as mock_get, patch("requests.head") as mock_head:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"token": "mock_token"}
        mock_head.return_value.status_code = 200
        mock_head.return_value.headers = {"docker-content-digest": "sha256:digest_1"}

        res1 = manager.check_container_update("caddy:latest", ["caddy@sha256:digest_1"])
        assert res1["status"] == "UP_TO_DATE"
        assert mock_head.call_count == 1

        # Age cache entry past 12 hours (12 * 3600 + 10)
        cache_key = "caddy:latest"
        assert cache_key in manager._update_cache
        manager._update_cache[cache_key]["checked_at"] = time.time() - (12 * 3600 + 10)

        # Now mock a new digest returned
        mock_head.return_value.headers = {"docker-content-digest": "sha256:digest_2"}
        res2 = manager.check_container_update("caddy:latest", ["caddy@sha256:digest_1"])
        assert res2["status"] == "UPDATE_AVAILABLE"
        assert res2["remote_digest"] == "sha256:digest_2"
        assert mock_head.call_count == 2


def test_check_stack_updates():
    manager = StackWatcherManager()
    manager._update_cache.clear()

    mock_stack = {
        "name": "smarthome_core",
        "containers": [
            {
                "name": "zigbee2mqtt",
                "image": "koenkk/zigbee2mqtt:latest",
                "repo_digests": ["koenkk/zigbee2mqtt@sha256:old_digest"],
            },
            {
                "name": "homeassistant",
                "image": "ghcr.io/home-assistant/home-assistant:stable",
                "repo_digests": ["ghcr.io/home-assistant/home-assistant@sha256:same_digest"],
            },
        ],
    }

    with patch.object(manager, "get_stack_details", return_value=mock_stack), \
         patch.object(manager, "check_container_update") as mock_check:
        mock_check.side_effect = [
            {
                "image": "koenkk/zigbee2mqtt:latest",
                "status": "UPDATE_AVAILABLE",
                "update_available": True,
                "remote_digest": "sha256:new_digest",
                "local_digest": "sha256:old_digest",
            },
            {
                "image": "ghcr.io/home-assistant/home-assistant:stable",
                "status": "UP_TO_DATE",
                "update_available": False,
                "remote_digest": "sha256:same_digest",
                "local_digest": "sha256:same_digest",
            },
        ]

        res = manager.check_stack_updates("smarthome_core")
        assert res["stack_name"] == "smarthome_core"
        assert res["updates_count"] == 1
        assert res["total_checked"] == 2
        assert len(res["containers"]) == 2
        assert res["containers"][0]["container_name"] == "zigbee2mqtt"
        assert res["containers"][0]["update_available"] is True
        assert res["containers"][1]["container_name"] == "homeassistant"
        assert res["containers"][1]["update_available"] is False


def test_check_stack_updates_not_found():
    manager = StackWatcherManager()
    with patch.object(manager, "get_stack_details", return_value=None):
        res = manager.check_stack_updates("nonexistent")
        assert res["stack_name"] == "nonexistent"
        assert res["updates_count"] == 0
        assert res["total_checked"] == 0
        assert res["containers"] == []
