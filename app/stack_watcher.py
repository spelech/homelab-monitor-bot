"""
Stack SRE Manager - Docker Socket Discovery, Health, & Container Inventory.
Discovers stacks and containers directly from the local Docker daemon socket,
and checks remote image registries for updates with 12-hour TTL caching.
"""

import os
import re
import json
import uuid
import logging
import time
import subprocess
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import docker
import requests
from sqlalchemy.orm import Session

from app.database import SessionLocal, Incident, StackAudit, Target
from app.transcript_logger import log_transcript_event

logger = logging.getLogger("StackWatcher")

ERROR_LOG_PATTERNS = re.compile(
    r"(?i)\b(error|fatal|panic|exception|traceback|critical|fail|failed|unhandled|refused|warn|warning)\b"
)
CRITICAL_LOG_PATTERN = re.compile(r"(?i)\b(fatal|panic|critical)\b")

BENIGN_FILTER_PATTERNS = [
    re.compile(r"node\s+--trace-deprecation", re.IGNORECASE),
    re.compile(r"OpenIddict\.Validation\.AspNetCore was not authenticated", re.IGNORECASE),
    re.compile(r"Transport error \(transient, will reconnect\): SSE connection closed", re.IGNORECASE),
    re.compile(r"status=401 stream=http", re.IGNORECASE),
    re.compile(r"WARNING Memory overcommit must be enabled", re.IGNORECASE),
    re.compile(r"Task documents\.tasks\.train_classifier.*ValueError\('No training data available\.'\)", re.IGNORECASE),
    re.compile(r"Plugin mysql_native_password reported:.*deprecated", re.IGNORECASE),
    re.compile(r"ERROR qdrant::common::telemetry_reporting: Failed to report telemetry", re.IGNORECASE),
    re.compile(r"Legend:\s+✓\s+ok\s+·\s+~\s+partial\s+·\s+✗\s+failed\s+·\s+--\s+skipped", re.IGNORECASE),
    re.compile(r"WRN Client Error address=.*status=401|WRN Client Error.*unauthorized", re.IGNORECASE),
    re.compile(r"Cannot get a reliable tag for this image \[sha256:", re.IGNORECASE),
    re.compile(r"Warning: You are sending unauthenticated requests to the HF Hub", re.IGNORECASE),
    re.compile(r"HTTPSConnectionPool\(host='.*\.plex\.direct'.*Read timed out", re.IGNORECASE),
]


def is_benign_noise(line: str) -> bool:
    """Checks if a log line matches known benign non-actionable homelab noise."""
    for pat in BENIGN_FILTER_PATTERNS:
        if pat.search(line):
            return True
    return False


def call_sre_ai_analyst(prompt: str) -> str:
    """
    Executes AI SRE analysis using configured AI executor (opencode server HTTP API or CLI / agy CLI).
    """
    current_executor = os.getenv("AI_EXECUTOR", "opencode").lower()
    output = None
    if current_executor == "opencode":
        try:
            from app.investigator import call_opencode_server
            output = call_opencode_server(prompt)
        except Exception as api_err:
            logger.warning(f"opencode HTTP API failed ({api_err}), falling back to CLI subprocess...")
            from app.investigator import OPENCODE_PATH, OPENCODE_PROVIDER_ID, OPENCODE_MODEL_ID
            cmd = [OPENCODE_PATH, "run", "--auto", "--model", f"{OPENCODE_PROVIDER_ID}/{OPENCODE_MODEL_ID}", prompt]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                output = result.stdout
            else:
                raise RuntimeError(f"opencode CLI error: {result.stderr}")
    else:
        from app.investigator import AGY_PATH, AGY_MODEL
        cmd = [AGY_PATH, "--model", AGY_MODEL, "--dangerously-skip-permissions", "--print", prompt]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            output = result.stdout
        else:
            raise RuntimeError(f"agy CLI error: {result.stderr}")

    try:
        from app.ai_usage import record_ai_usage
        from app.investigator import OPENCODE_MODEL_ID, AGY_MODEL
        model_name = OPENCODE_MODEL_ID if current_executor == "opencode" else AGY_MODEL
        record_ai_usage(
            incident_id=None,
            executor=current_executor,
            model_id=model_name,
            prompt_text=prompt,
            completion_text=output or "",
            status="SUCCESS" if output else "FAILED"
        )
    except Exception:
        pass

    return output



def parse_image_reference(image_str: str) -> Dict[str, str]:
    """
    Parses a docker image string (e.g. 'caddy:latest', 'ghcr.io/home-assistant/home-assistant:stable',
    'koenkk/zigbee2mqtt:1.35.0', 'quay.io/coreos/etcd:v3.5.0') into registry, repository, and tag.
    """
    if not image_str or image_str.strip() in ("", "<none>", "none", "<none>:<none>"):
        return {"registry": "", "repository": "", "tag": ""}

    # Strip digest suffix if present (e.g., repo:tag@sha256:...)
    clean_image = image_str.split("@")[0]

    parts = clean_image.split("/")
    if len(parts) == 1:
        # Official library image e.g. "caddy:latest" or "caddy"
        registry = "registry-1.docker.io"
        repo_tag = parts[0]
        if ":" in repo_tag:
            name, tag = repo_tag.split(":", 1)
        else:
            name, tag = repo_tag, "latest"
        repository = f"library/{name}"
    elif len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        # Domain or host registry e.g. "ghcr.io/org/repo:tag"
        registry = parts[0]
        repo_tag = "/".join(parts[1:])
        if ":" in repo_tag:
            repository, tag = repo_tag.rsplit(":", 1)
        else:
            repository, tag = repo_tag, "latest"
    else:
        # Docker Hub user image e.g. "koenkk/zigbee2mqtt:latest"
        registry = "registry-1.docker.io"
        repo_tag = "/".join(parts)
        if ":" in repo_tag:
            repository, tag = repo_tag.rsplit(":", 1)
        else:
            repository, tag = repo_tag, "latest"

    return {"registry": registry, "repository": repository, "tag": tag}


class StackWatcherManager:
    CACHE_TTL_SECONDS = 12 * 3600  # 12 hours

    def __init__(self, client: Optional[docker.DockerClient] = None):
        self._client = client
        self._update_cache: Dict[str, Any] = {}

    @property
    def client(self) -> Optional[docker.DockerClient]:
        return self._client

    @client.setter
    def client(self, value: Optional[docker.DockerClient]):
        self._client = value

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
        repo_digests = []
        if hasattr(container, "image") and container.image:
            image_tags = getattr(container.image, "tags", []) or []
            image_id = getattr(container.image, "id", "") or ""
            image_attrs = getattr(container.image, "attrs", {}) or {}
            repo_digests = image_attrs.get("RepoDigests", []) or []

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
            "repo_digests": repo_digests,
            "status": status,
            "health": health_status,
            "started_at": state.get("StartedAt", ""),
            "created_at": attrs.get("Created", ""),
            "ports": ports,
            "labels": labels,
        }

    def _get_registry_token(self, registry: str, repository: str) -> Optional[str]:
        if registry in ("registry-1.docker.io", "docker.io"):
            url = f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repository}:pull"
        elif registry == "ghcr.io":
            url = f"https://ghcr.io/token?service=ghcr.io&scope=repository:{repository}:pull"
        elif registry == "quay.io":
            url = f"https://quay.io/v2/auth?service=quay.io&scope=repository:{repository}:pull"
        else:
            url = f"https://{registry}/token?service={registry}&scope=repository:{repository}:pull"

        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("token") or data.get("access_token")
        return None

    def _fetch_remote_digest(
        self, registry: str, repository: str, tag: str, token: Optional[str] = None
    ) -> Optional[str]:
        headers = {
            "Accept": (
                "application/vnd.docker.distribution.manifest.v2+json, "
                "application/vnd.docker.distribution.manifest.list.v2+json, "
                "application/vnd.oci.image.manifest.v1+json, "
                "application/vnd.oci.image.index.v1+json"
            )
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        manifest_url = f"https://{registry}/v2/{repository}/manifests/{tag}"

        try:
            # First try HEAD
            resp = requests.head(manifest_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                digest = resp.headers.get("docker-content-digest") or resp.headers.get(
                    "Docker-Content-Digest"
                )
                if digest:
                    return digest

            # If HEAD didn't yield digest or wasn't 200, try GET
            resp = requests.get(manifest_url, headers=headers, timeout=5)
            if resp.status_code == 200:
                digest = resp.headers.get("docker-content-digest") or resp.headers.get(
                    "Docker-Content-Digest"
                )
                return digest
        except Exception as net_err:
            logger.debug(f"Network error fetching digest for {registry}/{repository}:{tag}: {net_err}")
            return None
        return None

    def check_container_update(
        self,
        image_tag: str,
        local_repo_digests: Optional[List[str]] = None,
        local_image_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Checks whether an update is available for the given image tag compared against local digests.
        Uses a 12-hour memory cache.
        """
        if not image_tag or image_tag.strip() in ("", "<none>", "none", "<none>:<none>"):
            return {
                "image": image_tag,
                "status": "LOCAL_IMAGE",
                "update_available": False,
                "remote_digest": None,
                "local_digest": None,
            }

        # Extract local digest from local_repo_digests or local_image_id
        local_digest = None
        if local_repo_digests:
            for d in local_repo_digests:
                if "@" in d:
                    local_digest = d.split("@", 1)[1]
                    break
                elif d.startswith("sha256:"):
                    local_digest = d
                    break
        if not local_digest and local_image_id:
            local_digest = local_image_id

        # Check cache
        now = time.time()
        cached_entry = self._update_cache.get(image_tag)
        if cached_entry and (now - cached_entry.get("checked_at", 0) < self.CACHE_TTL_SECONDS):
            remote_digest = cached_entry.get("remote_digest")
            if remote_digest:
                is_match = False
                if local_repo_digests:
                    for d in local_repo_digests:
                        if remote_digest in d or d == remote_digest:
                            is_match = True
                            break
                elif local_digest and remote_digest == local_digest:
                    is_match = True

                return {
                    "image": image_tag,
                    "status": "UP_TO_DATE" if is_match else "UPDATE_AVAILABLE",
                    "update_available": not is_match,
                    "remote_digest": remote_digest,
                    "local_digest": local_digest,
                    "cached": True,
                }
            return cached_entry

        parsed = parse_image_reference(image_tag)
        if not parsed["registry"] or not parsed["repository"]:
            return {
                "image": image_tag,
                "status": "LOCAL_IMAGE",
                "update_available": False,
                "remote_digest": None,
                "local_digest": local_digest,
            }

        try:
            token = self._get_registry_token(parsed["registry"], parsed["repository"])
            remote_digest = self._fetch_remote_digest(
                parsed["registry"], parsed["repository"], parsed["tag"], token=token
            )
            if not remote_digest:
                return {
                    "image": image_tag,
                    "status": "UNKNOWN",
                    "update_available": False,
                    "remote_digest": None,
                    "local_digest": local_digest,
                }

            is_match = False
            if local_repo_digests:
                for d in local_repo_digests:
                    if remote_digest in d or d == remote_digest:
                        is_match = True
                        break
            elif local_digest and remote_digest == local_digest:
                is_match = True

            status = "UP_TO_DATE" if is_match else "UPDATE_AVAILABLE"
            result = {
                "image": image_tag,
                "status": status,
                "update_available": not is_match,
                "remote_digest": remote_digest,
                "local_digest": local_digest,
                "checked_at": now,
            }
            self._update_cache[image_tag] = result
            return result
        except Exception as e:
            logger.warning(f"Error checking update for {image_tag}: {e}")
            return {
                "image": image_tag,
                "status": "UNKNOWN",
                "update_available": False,
                "remote_digest": None,
                "local_digest": local_digest,
                "error": str(e),
            }

    def check_stack_updates(self, stack_name: str) -> Dict[str, Any]:
        """
        Checks container image updates for all containers in a given stack.
        """
        stack = self.get_stack_details(stack_name)
        if not stack:
            return {
                "stack_name": stack_name,
                "updates_count": 0,
                "total_checked": 0,
                "containers": [],
            }

        containers_res = []
        updates_count = 0

        for c in stack.get("containers", []):
            image_tag = c.get("image", "")
            repo_digests = c.get("repo_digests", [])
            image_id = c.get("image_id", "")
            try:
                c_update = self.check_container_update(image_tag, repo_digests, image_id)
            except Exception as update_err:
                logger.warning(f"Error checking update for container {c.get('name')}: {update_err}")
                c_update = {"status": "UNKNOWN", "update_available": False}

            if c_update.get("update_available"):
                updates_count += 1
            containers_res.append(
                {
                    "container_name": c.get("name", ""),
                    "image": image_tag,
                    "status": c_update.get("status", "UNKNOWN"),
                    "update_available": c_update.get("update_available", False),
                    "remote_digest": c_update.get("remote_digest"),
                    "local_digest": c_update.get("local_digest"),
                }
            )

        return {
            "stack_name": stack_name,
            "updates_count": updates_count,
            "total_checked": len(containers_res),
            "containers": containers_res,
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

    @staticmethod
    def _is_container_running_and_healthy(container: Any) -> bool:
        attrs = getattr(container, "attrs", {}) or {}
        state = attrs.get("State")
        if not isinstance(state, dict) or not state:
            return False

        # Running status check
        is_running = state.get("Running") is True or state.get("Status") == "running" or getattr(container, "status", "") == "running"
        if not is_running:
            return False

        # Explicitly crashed or dead or restarting
        if state.get("Restarting") is True or state.get("Dead") is True:
            return False
        if state.get("Status") in ["exited", "dead", "restarting"]:
            return False

        # Healthcheck check if defined
        health = state.get("Health")
        if isinstance(health, dict):
            health_status = str(health.get("Status", "")).lower()
            if health_status == "unhealthy":
                return False
            if health_status in ["healthy", "none", ""]:
                return True
            return False

        return True

    def audit_stack_logs(self, stack_name: str, db: Optional[Session] = None, notify: bool = True) -> Dict[str, Any]:
        """
        Collects logs for all containers in the given stack, filters 24h error/warning lines,
        runs AI triage to determine if an issue is actionable, creates PENDING_USER Incidents
        with origin='sre_daily_audit' and StackAudit records, and triggers push notifications.
        """
        client = self._get_client()
        if client is None:
            return {
                "stack_name": stack_name,
                "status": "UNKNOWN",
                "error_count": 0,
                "containers_checked": 0,
                "summary": "Docker daemon unavailable",
            }

        try:
            all_containers = client.containers.list(all=True)
        except Exception as e:
            logger.error(f"Error querying containers for stack audit '{stack_name}': {e}")
            return {
                "stack_name": stack_name,
                "status": "UNKNOWN",
                "error_count": 0,
                "containers_checked": 0,
                "summary": f"Error querying Docker: {e}",
            }

        # Filter containers belonging to stack_name
        stack_containers = []
        for c in all_containers:
            attrs = getattr(c, "attrs", {}) or {}
            labels = attrs.get("Config", {}).get("Labels", {}) or {}
            project = labels.get("com.docker.compose.project")
            c_name = getattr(c, "name", "") or attrs.get("Name", "").lstrip("/")

            # Skip monitorbot container to prevent loops
            if "monitorbot" in c_name:
                continue

            if project == stack_name:
                stack_containers.append(c)
            elif stack_name == "standalone" and not project:
                stack_containers.append(c)

        close_db_on_exit = False
        if db is None:
            db = SessionLocal()
            close_db_on_exit = True

        try:
            if not stack_containers:
                return {
                    "stack_name": stack_name,
                    "status": "HEALTHY",
                    "incident_id": None,
                    "incident_ids": [],
                    "error_count": 0,
                    "containers_checked": 0,
                    "summary": f"No containers found for stack '{stack_name}'.",
                }

            container_errors: Dict[str, List[str]] = {}
            total_error_count = 0
            since_ts = int((datetime.utcnow() - timedelta(hours=24)).timestamp())

            for c in stack_containers:
                c_name = getattr(c, "name", "") or getattr(c, "id", "unknown")
                try:
                    raw_logs = c.logs(tail=500, since=since_ts)
                    if isinstance(raw_logs, bytes):
                        log_text = raw_logs.decode("utf-8", errors="replace")
                    else:
                        log_text = str(raw_logs)

                    matched_lines = []
                    for line in log_text.splitlines():
                        if ERROR_LOG_PATTERNS.search(line) and not is_benign_noise(line):
                            matched_lines.append(line.strip())

                    if matched_lines:
                        container_errors[c_name] = matched_lines
                        total_error_count += len(matched_lines)
                except Exception as log_err:
                    logger.warning(f"Failed to fetch logs for container '{c_name}': {log_err}")

            if total_error_count == 0:
                summary = f"Stack '{stack_name}' is healthy. No critical errors detected across {len(stack_containers)} container(s) in the last 24h."
                audit = StackAudit(
                    id=str(uuid.uuid4()),
                    stack_name=stack_name,
                    status="HEALTHY",
                    summary=summary,
                    error_count="0",
                    containers_checked=str(len(stack_containers)),
                    created_at=datetime.utcnow(),
                )
                db.add(audit)
                db.commit()

                return {
                    "stack_name": stack_name,
                    "status": "HEALTHY",
                    "incident_id": None,
                    "incident_ids": [],
                    "error_count": 0,
                    "containers_checked": len(stack_containers),
                    "summary": summary,
                }

            # Build error log snippet for AI analysis
            log_snippets = []
            for c_name, lines in container_errors.items():
                snippet = f"=== Container: {c_name} (Errors/Warnings: {len(lines)}) ===\n" + "\n".join(lines[-30:])
                log_snippets.append(snippet)
            aggregated_errors = "\n\n".join(log_snippets)

            from app.prompts import build_sre_audit_prompt
            prompt = build_sre_audit_prompt(stack_name, aggregated_errors)

            ai_output = None
            try:
                ai_output = call_sre_ai_analyst(prompt)
            except Exception as ai_err:
                logger.error(f"AI SRE analyst invocation failed for stack '{stack_name}': {ai_err}")
                ai_output = None

            parsed_json = None
            if ai_output:
                try:
                    json_match = re.search(r"\{.*\}", ai_output, re.DOTALL)
                    if json_match:
                        parsed_json = json.loads(json_match.group(0))
                except Exception as parse_e:
                    logger.warning(f"Failed to parse AI output for stack '{stack_name}': {parse_e}")

            actionable_incidents: List[Incident] = []
            actionable_incident_ids: List[str] = []
            overall_summary = ""
            primary_root_cause = "Container errors detected during daily SRE audit."
            primary_proposed_fix = ""
            primary_category = "unknown"

            if parsed_json and isinstance(parsed_json.get("containers"), dict) and len(parsed_json["containers"]) > 0:
                overall_summary = parsed_json.get("overall_summary", "")
                for c_name, c_diag in parsed_json["containers"].items():
                    if not isinstance(c_diag, dict):
                        continue
                    c_action_required = bool(c_diag.get("action_required", True))
                    c_root_cause = c_diag.get("root_cause", "Container errors detected during daily SRE audit.")
                    c_proposed_fix = c_diag.get("proposed_fix", "")
                    c_category = str(c_diag.get("category", "unknown")).lower()

                    # Find matching container in stack_containers
                    cont_obj = None
                    for sc in stack_containers:
                        sc_name = getattr(sc, "name", "") or getattr(sc, "attrs", {}).get("Name", "").lstrip("/")
                        sc_id = getattr(sc, "id", "") or getattr(sc, "attrs", {}).get("Id", "")
                        if sc_name == c_name or sc_id == c_name or sc_name.endswith(f"_{c_name}_1") or sc_name.endswith(f"-{c_name}-1"):
                            cont_obj = sc
                            break

                    # If container is currently running & healthy, suppress action_required unless crashed or degraded
                    if cont_obj is not None and self._is_container_running_and_healthy(cont_obj):
                        cont_lines = container_errors.get(c_name, [])
                        if not any(CRITICAL_LOG_PATTERN.search(line) for line in cont_lines):
                            c_action_required = False

                    if not primary_root_cause or primary_root_cause == "Container errors detected during daily SRE audit.":
                        primary_root_cause = c_root_cause
                        primary_proposed_fix = c_proposed_fix
                        primary_category = c_category

                    if c_action_required:
                        # Ensure Target exists
                        target = db.query(Target).filter(Target.id == c_name).first()
                        if not target:
                            target = Target(id=c_name, type="docker", ignored_until=None)
                            db.add(target)
                            db.commit()
                            db.refresh(target)

                        c_error_logs = "\n".join(container_errors[c_name][-30:]) if c_name in container_errors else aggregated_errors

                        incident_id = str(uuid.uuid4())
                        incident = Incident(
                            id=incident_id,
                            target_id=c_name,
                            status="PENDING_USER",
                            error_logs=c_error_logs,
                            root_cause=c_root_cause,
                            proposed_fix=c_proposed_fix,
                            category=c_category,
                            stack_name=stack_name,
                            origin="sre_daily_audit",
                            created_at=datetime.utcnow(),
                        )
                        db.add(incident)
                        actionable_incidents.append(incident)
                        actionable_incident_ids.append(incident_id)

                        # Record transcript events
                        log_transcript_event(incident_id, "PROMPT_GENERATED", {
                            "stack_name": stack_name,
                            "target_id": c_name,
                            "prompt": prompt,
                            "error_count": len(container_errors.get(c_name, [])),
                            "containers_checked": len(stack_containers),
                        })
                        log_transcript_event(incident_id, "AI_THINKING_RAW", {
                            "raw_output": ai_output,
                            "executor": os.getenv("AI_EXECUTOR", "opencode"),
                        })
                        log_transcript_event(incident_id, "DIAGNOSIS_PARSED", {
                            "root_cause": c_root_cause,
                            "proposed_fix": c_proposed_fix,
                            "category": c_category,
                            "action_required": c_action_required,
                        })
            else:
                # Flat format backward compatibility / fallback
                root_cause = "Container errors detected during daily SRE audit."
                proposed_fix = ""
                category = "unknown"
                action_required = True

                if parsed_json:
                    root_cause = parsed_json.get("root_cause", root_cause)
                    proposed_fix = parsed_json.get("proposed_fix", proposed_fix)
                    category = parsed_json.get("category", category)
                    action_required = bool(parsed_json.get("action_required", True))

                primary_root_cause = root_cause
                primary_proposed_fix = proposed_fix
                primary_category = category
                overall_summary = root_cause

                primary_target_id = list(container_errors.keys())[0] if container_errors else stack_name
                cont_obj = None
                for sc in stack_containers:
                    sc_name = getattr(sc, "name", "") or getattr(sc, "attrs", {}).get("Name", "").lstrip("/")
                    sc_id = getattr(sc, "id", "") or getattr(sc, "attrs", {}).get("Id", "")
                    if sc_name == primary_target_id or sc_id == primary_target_id or sc_name.endswith(f"_{primary_target_id}_1") or sc_name.endswith(f"-{primary_target_id}-1"):
                        cont_obj = sc
                        break

                if cont_obj is not None and self._is_container_running_and_healthy(cont_obj):
                    cont_lines = container_errors.get(primary_target_id, []) or [aggregated_errors]
                    if not any(CRITICAL_LOG_PATTERN.search(line) for line in cont_lines):
                        action_required = False

                if action_required:
                    # Ensure Target exists
                    target = db.query(Target).filter(Target.id == primary_target_id).first()
                    if not target:
                        target = Target(id=primary_target_id, type="docker", ignored_until=None)
                        db.add(target)
                        db.commit()
                        db.refresh(target)

                    incident_id = str(uuid.uuid4())
                    incident = Incident(
                        id=incident_id,
                        target_id=primary_target_id,
                        status="PENDING_USER",
                        error_logs=aggregated_errors,
                        root_cause=root_cause,
                        proposed_fix=proposed_fix,
                        category=str(category).lower(),
                        stack_name=stack_name,
                        origin="sre_daily_audit",
                        created_at=datetime.utcnow(),
                    )
                    db.add(incident)
                    actionable_incidents.append(incident)
                    actionable_incident_ids.append(incident_id)

                    # Record transcript events
                    log_transcript_event(incident_id, "PROMPT_GENERATED", {
                        "stack_name": stack_name,
                        "target_id": primary_target_id,
                        "prompt": prompt,
                        "error_count": total_error_count,
                        "containers_checked": len(stack_containers),
                    })
                    log_transcript_event(incident_id, "AI_THINKING_RAW", {
                        "raw_output": ai_output,
                        "executor": os.getenv("AI_EXECUTOR", "opencode"),
                    })
                    log_transcript_event(incident_id, "DIAGNOSIS_PARSED", {
                        "root_cause": root_cause,
                        "proposed_fix": proposed_fix,
                        "category": category,
                        "action_required": action_required,
                    })

            if actionable_incident_ids:
                audit_summary = overall_summary or primary_root_cause
                audit = StackAudit(
                    id=str(uuid.uuid4()),
                    stack_name=stack_name,
                    status="ACTION_REQUIRED",
                    summary=audit_summary,
                    error_count=str(total_error_count),
                    containers_checked=str(len(stack_containers)),
                    created_at=datetime.utcnow(),
                )
                db.add(audit)
                db.commit()

                # Trigger notifications
                if notify:
                    for inc in actionable_incidents:
                        try:
                            from app.notifier import send_incident_notification
                            send_incident_notification(inc.id)
                        except Exception as notif_err:
                            logger.error(f"Failed to send incident notification for SRE audit {inc.id}: {notif_err}")

                return {
                    "stack_name": stack_name,
                    "status": "ACTION_REQUIRED",
                    "incident_id": actionable_incident_ids[0],
                    "incident_ids": actionable_incident_ids,
                    "error_count": total_error_count,
                    "containers_checked": len(stack_containers),
                    "root_cause": primary_root_cause,
                    "proposed_fix": primary_proposed_fix,
                    "category": primary_category,
                    "summary": audit_summary,
                }
            else:
                summary_text = overall_summary or primary_root_cause or "Non-actionable / transient warnings detected."
                audit = StackAudit(
                    id=str(uuid.uuid4()),
                    stack_name=stack_name,
                    status="WARNING",
                    summary=summary_text,
                    error_count=str(total_error_count),
                    containers_checked=str(len(stack_containers)),
                    created_at=datetime.utcnow(),
                )
                db.add(audit)
                db.commit()

                return {
                    "stack_name": stack_name,
                    "status": "WARNING",
                    "incident_id": None,
                    "incident_ids": [],
                    "error_count": total_error_count,
                    "containers_checked": len(stack_containers),
                    "root_cause": primary_root_cause,
                    "proposed_fix": primary_proposed_fix,
                    "category": primary_category,
                    "summary": summary_text,
                }

        finally:
            if close_db_on_exit:
                db.close()

    def audit_all_stacks(self, send_digest: bool = True) -> List[Dict[str, Any]]:
        """
        Audits logs across all discovered Docker Compose stacks on the host.
        """
        stacks = self.discover_stacks()
        results = []
        for stack in stacks:
            stack_name = stack["name"]
            try:
                res = self.audit_stack_logs(stack_name, notify=False)
                results.append(res)
            except Exception as e:
                logger.error(f"Error auditing stack '{stack_name}': {e}")
                results.append({
                    "stack_name": stack_name,
                    "status": "FAILED",
                    "error": str(e),
                    "error_count": 0,
                    "containers_checked": 0,
                })

        if send_digest:
            try:
                from app.notifier import send_sre_digest_notification
                send_sre_digest_notification(results)
            except Exception as notif_err:
                logger.error(f"Failed to send SRE digest notification: {notif_err}")

        return results


# Global singleton instance
stack_watcher_manager = StackWatcherManager()

