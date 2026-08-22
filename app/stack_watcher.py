"""
Stack SRE Manager - Docker Socket Discovery, Health, & Container Inventory.
Discovers stacks and containers directly from the local Docker daemon socket.
"""

import logging
from typing import Any, Dict, List, Optional
import docker

logger = logging.getLogger("StackWatcher")


class StackWatcherManager:
    def __init__(self, client: Optional[docker.DockerClient] = None):
        self._client = client
        self._update_cache: Dict[str, Any] = {}

    def _get_client(self) -> Optional[docker.DockerClient]:
        if self._client is not None:
            return self._client
        try:
            return docker.from_env()
        except Exception as e:
            logger.error(f"Failed to connect to Docker daemon: {e}")
            return None

    def _parse_ports(self, attrs: Dict[str, Any]) -> List[str]:
        ports_list: List[str] = []
        network_settings = attrs.get("NetworkSettings", {}) or {}
        ports_dict = network_settings.get("Ports", {}) or {}

        for container_port, host_bindings in ports_dict.items():
            if host_bindings and isinstance(host_bindings, list):
                for binding in host_bindings:
                    if isinstance(binding, dict) and "HostPort" in binding:
                        ports_list.append(f"{binding['HostPort']}->{container_port}")
                    else:
                        ports_list.append(container_port)
            else:
                ports_list.append(container_port)

        return sorted(ports_list)

    def _parse_container(self, container: Any) -> Dict[str, Any]:
        attrs = getattr(container, "attrs", {}) or {}
        state = attrs.get("State", {}) or {}
        config = attrs.get("Config", {}) or {}
        labels = config.get("Labels", {}) or {}

        health_data = state.get("Health", {}) or {}
        health_status = health_data.get("Status", "none")

        image_tags = []
        image_id = ""
        if hasattr(container, "image") and container.image:
            image_tags = getattr(container.image, "tags", []) or []
            image_id = getattr(container.image, "id", "") or ""

        image_name = config.get("Image", "")
        if not image_name and image_tags:
            image_name = image_tags[0]

        container_id = getattr(container, "id", "") or attrs.get("Id", "")
        container_name = getattr(container, "name", "") or attrs.get("Name", "").lstrip("/")
        status = getattr(container, "status", "") or state.get("Status", "")

        service_name = labels.get("com.docker.compose.service") or container_name
        project_name = labels.get("com.docker.compose.project") or "standalone"
        working_dir = labels.get("com.docker.compose.project.working_dir", "")
        config_files = labels.get("com.docker.compose.project.config_files", "")

        ports = self._parse_ports(attrs)

        return {
            "id": container_id,
            "name": container_name,
            "service": service_name,
            "project": project_name,
            "working_dir": working_dir,
            "config_files": config_files,
            "image": image_name,
            "image_id": image_id,
            "image_tags": image_tags,
            "status": status,
            "health": health_status,
            "started_at": state.get("StartedAt", ""),
            "created_at": attrs.get("Created", ""),
            "ports": ports,
            "labels": labels,
        }

    def discover_stacks(self) -> List[Dict[str, Any]]:
        client = self._get_client()
        if client is None:
            return []

        try:
            containers = client.containers.list(all=True)
        except Exception as e:
            logger.error(f"Error querying Docker containers: {e}")
            return []

        projects: Dict[str, List[Dict[str, Any]]] = {}

        for c in containers:
            try:
                parsed = self._parse_container(c)
                project = parsed["project"]
                if project not in projects:
                    projects[project] = []
                projects[project].append(parsed)
            except Exception as e:
                logger.warning(f"Error parsing container {getattr(c, 'name', 'unknown')}: {e}")

        stacks: List[Dict[str, Any]] = []

        for project_name, container_list in projects.items():
            total = len(container_list)
            running = sum(1 for c in container_list if c["status"] == "running")
            unhealthy = sum(
                1
                for c in container_list
                if c["health"] == "unhealthy" or c["status"] in ("dead", "restarting")
            )
            healthy = sum(
                1
                for c in container_list
                if c["health"] == "healthy"
                or (c["status"] == "running" and c["health"] != "unhealthy")
            )

            # Determine stack-level status
            if unhealthy > 0:
                stack_status = "unhealthy"
            elif running == total and total > 0:
                stack_status = "healthy"
            elif running > 0:
                stack_status = "degraded"
            else:
                stack_status = "stopped"

            working_dir = ""
            config_files = ""
            for c in container_list:
                if c.get("working_dir"):
                    working_dir = c["working_dir"]
                if c.get("config_files"):
                    config_files = c["config_files"]

            stacks.append(
                {
                    "name": project_name,
                    "working_dir": working_dir,
                    "config_files": config_files,
                    "status": stack_status,
                    "total_containers": total,
                    "running_containers": running,
                    "healthy_containers": healthy,
                    "unhealthy_containers": unhealthy,
                    "containers": container_list,
                }
            )

        # Sort stacks alphabetically by name
        stacks.sort(key=lambda s: s["name"])
        return stacks

    def get_stack_details(self, stack_name: str) -> Optional[Dict[str, Any]]:
        stacks = self.discover_stacks()
        for stack in stacks:
            if stack["name"] == stack_name:
                return stack
        return None


# Global singleton instance
stack_watcher_manager = StackWatcherManager()
