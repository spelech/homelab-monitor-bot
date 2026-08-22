from unittest.mock import MagicMock, patch
import pytest
from app.stack_watcher import StackWatcherManager, stack_watcher_manager

def test_discover_stacks_from_docker_socket():
    mock_container_1 = MagicMock()
    mock_container_1.id = "c11111111111"
    mock_container_1.name = "zigbee2mqtt"
    mock_container_1.status = "running"
    mock_container_1.attrs = {
        "State": {"Status": "running", "Health": {"Status": "healthy"}, "StartedAt": "2026-08-20T10:00:00Z"},
        "Config": {"Image": "koenkk/zigbee2mqtt:latest", "Labels": {
            "com.docker.compose.project": "smarthome_core",
            "com.docker.compose.service": "zigbee2mqtt",
            "com.docker.compose.project.working_dir": "/containers/smarthome_core",
            "com.docker.compose.project.config_files": "/containers/smarthome_core/docker-compose.yaml"
        }},
        "NetworkSettings": {"Ports": {"8080/tcp": [{"HostPort": "8120"}]}}
    }
    mock_container_1.image.tags = ["koenkk/zigbee2mqtt:latest"]
    mock_container_1.image.id = "sha256:111111111111"

    mock_container_2 = MagicMock()
    mock_container_2.id = "c22222222222"
    mock_container_2.name = "caddy"
    mock_container_2.status = "running"
    mock_container_2.attrs = {
        "State": {"Status": "running", "Health": {"Status": "none"}, "StartedAt": "2026-08-20T10:00:00Z"},
        "Config": {"Image": "lucaslorentz/caddy-docker-proxy:2.8.11-alpine", "Labels": {
            "com.docker.compose.project": "webservices",
            "com.docker.compose.service": "caddy",
            "com.docker.compose.project.working_dir": "/containers/webservices"
        }},
        "NetworkSettings": {"Ports": {"443/tcp": [{"HostPort": "443"}]}}
    }
    mock_container_2.image.tags = ["lucaslorentz/caddy-docker-proxy:2.8.11-alpine"]
    mock_container_2.image.id = "sha256:222222222222"

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_container_1, mock_container_2]

    with patch("docker.from_env", return_value=mock_docker):
        manager = StackWatcherManager()
        stacks = manager.discover_stacks()
        assert len(stacks) == 2
        stack_names = [s["name"] for s in stacks]
        assert "smarthome_core" in stack_names
        assert "webservices" in stack_names

        smarthome = next(s for s in stacks if s["name"] == "smarthome_core")
        assert smarthome["total_containers"] == 1
        assert smarthome["healthy_containers"] == 1
        assert smarthome["status"] == "healthy"
        assert smarthome["config_files"] == "/containers/smarthome_core/docker-compose.yaml"
        assert smarthome["containers"][0]["name"] == "zigbee2mqtt"
        assert smarthome["containers"][0]["ports"] == ["8120->8080/tcp"]

def test_get_stack_details():
    mock_container = MagicMock()
    mock_container.id = "c33333333333"
    mock_container.name = "homeassistant"
    mock_container.status = "running"
    mock_container.attrs = {
        "State": {"Status": "running", "Health": {"Status": "healthy"}, "StartedAt": "2026-08-20T10:00:00Z"},
        "Config": {"Image": "homeassistant/home-assistant:stable", "Labels": {
            "com.docker.compose.project": "smarthome_core",
            "com.docker.compose.service": "homeassistant",
            "com.docker.compose.project.working_dir": "/containers/smarthome_core"
        }},
        "NetworkSettings": {"Ports": {"8123/tcp": [{"HostPort": "8123"}]}}
    }
    mock_container.image.tags = ["homeassistant/home-assistant:stable"]
    mock_container.image.id = "sha256:333333333333"

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_container]

    manager = StackWatcherManager(client=mock_docker)
    details = manager.get_stack_details("smarthome_core")
    assert details is not None
    assert details["name"] == "smarthome_core"
    assert details["total_containers"] == 1
    assert len(details["containers"]) == 1
    assert details["containers"][0]["service"] == "homeassistant"

    non_existent = manager.get_stack_details("non_existent_stack")
    assert non_existent is None

def test_standalone_containers_and_unhealthy_status():
    mock_container_unhealthy = MagicMock()
    mock_container_unhealthy.id = "c44444444444"
    mock_container_unhealthy.name = "failing_app"
    mock_container_unhealthy.status = "running"
    mock_container_unhealthy.attrs = {
        "State": {"Status": "running", "Health": {"Status": "unhealthy"}, "StartedAt": "2026-08-20T10:00:00Z"},
        "Config": {"Image": "failing/app:latest", "Labels": {
            "com.docker.compose.project": "media",
            "com.docker.compose.service": "failing_app",
        }},
        "NetworkSettings": {"Ports": {}}
    }
    mock_container_unhealthy.image.tags = ["failing/app:latest"]
    mock_container_unhealthy.image.id = "sha256:444444444444"

    mock_container_standalone = MagicMock()
    mock_container_standalone.id = "c55555555555"
    mock_container_standalone.name = "standalone_box"
    mock_container_standalone.status = "exited"
    mock_container_standalone.attrs = {
        "State": {"Status": "exited", "StartedAt": "2026-08-19T10:00:00Z"},
        "Config": {"Image": "standalone:latest", "Labels": {}},
        "NetworkSettings": {"Ports": {"9000/tcp": None}}
    }
    mock_container_standalone.image.tags = ["standalone:latest"]
    mock_container_standalone.image.id = "sha256:555555555555"

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [mock_container_unhealthy, mock_container_standalone]

    manager = StackWatcherManager(client=mock_docker)
    stacks = manager.discover_stacks()
    
    media_stack = next(s for s in stacks if s["name"] == "media")
    assert media_stack["unhealthy_containers"] == 1
    assert media_stack["status"] == "unhealthy"

    standalone_stack = next(s for s in stacks if s["name"] == "standalone")
    assert standalone_stack["total_containers"] == 1
    assert standalone_stack["running_containers"] == 0
    assert standalone_stack["containers"][0]["ports"] == ["9000/tcp"]

def test_degraded_stack_status():
    # 1 running, 1 exited, 0 unhealthy -> degraded status
    c1 = MagicMock()
    c1.id = "d1"
    c1.name = "db"
    c1.status = "running"
    c1.attrs = {
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "Config": {"Image": "", "Labels": {"com.docker.compose.project": "cloud"}},
        "NetworkSettings": {"Ports": {"5432/tcp": ["invalid_binding_format"]}}
    }
    c1.image.tags = ["postgres:16"]
    c1.image.id = "sha256:db"

    c2 = MagicMock()
    c2.id = "d2"
    c2.name = "web"
    c2.status = "exited"
    c2.attrs = {
        "State": {"Status": "exited", "Health": {"Status": "none"}},
        "Config": {"Image": "web:latest", "Labels": {"com.docker.compose.project": "cloud"}},
        "NetworkSettings": {"Ports": {}}
    }
    c2.image.tags = ["web:latest"]
    c2.image.id = "sha256:web"

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [c1, c2]

    manager = StackWatcherManager(client=mock_docker)
    stacks = manager.discover_stacks()
    cloud = next(s for s in stacks if s["name"] == "cloud")
    assert cloud["status"] == "degraded"
    assert cloud["running_containers"] == 1
    assert cloud["total_containers"] == 2
    assert cloud["containers"][0]["image"] == "postgres:16"
    assert cloud["containers"][0]["ports"] == ["5432/tcp"]

def test_docker_containers_list_exception_handled():
    mock_docker = MagicMock()
    mock_docker.containers.list.side_effect = Exception("Docker socket timeout")

    manager = StackWatcherManager(client=mock_docker)
    assert manager.discover_stacks() == []

def test_container_parsing_exception_handled():
    bad_container = MagicMock()
    bad_container.name = "broken"
    # Accessing attrs raises exception
    type(bad_container).attrs = property(lambda self: (_ for _ in ()).throw(ValueError("Corrupt container attrs")))

    mock_docker = MagicMock()
    mock_docker.containers.list.return_value = [bad_container]

    manager = StackWatcherManager(client=mock_docker)
    stacks = manager.discover_stacks()
    assert stacks == []

def test_docker_connection_failure_handled():
    with patch("docker.from_env", side_effect=Exception("Docker daemon not running")):
        manager = StackWatcherManager()
        stacks = manager.discover_stacks()
        assert stacks == []
        assert manager.get_stack_details("anything") is None

def test_singleton_instance_available():
    assert stack_watcher_manager is not None
    assert isinstance(stack_watcher_manager, StackWatcherManager)
