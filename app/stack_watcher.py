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
from datetime import datetime
from typing import Any, Dict, List, Optional
import docker
import requests
from sqlalchemy.orm import Session

from app.database import SessionLocal, Incident, StackAudit, Target

logger = logging.getLogger("StackWatcher")

ERROR_LOG_PATTERNS = re.compile(
    r"(?i)\b(error|fatal|panic|exception|traceback|critical|fail|failed|unhandled|refused|warn|warning)\b"
)


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
            opencode_path = os.getenv("OPENCODE_PATH", "/home/steve/.nvm/versions/node/v22.17.0/bin/opencode")
            provider_id = os.getenv("OPENCODE_PROVIDER_ID", "litellm")
            model_id = os.getenv("OPENCODE_MODEL_ID", "qwen3.5-flash-02-23")
            cmd = [opencode_path, "run", "--auto", "--model", f"{provider_id}/{model_id}", prompt]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if result.returncode == 0:
                output = result.stdout
            else:
                raise RuntimeError(f"opencode CLI error: {result.stderr}")
    else:
        agy_path = os.getenv("AGY_PATH", "/home/steve/.local/bin/agy")
        cmd = [agy_path, "--model", "gemini-3.5-flash-medium", "--dangerously-skip-permissions", "--print", prompt]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0:
            output = result.stdout
        else:
            raise RuntimeError(f"agy CLI error: {result.stderr}")

    try:
        from app.ai_usage import record_ai_usage
        model_name = os.getenv("OPENCODE_MODEL_ID", "qwen3.5-flash-02-23") if current_executor == "opencode" else "gemini-3.5-flash-medium"
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
            c_update = self.check_container_update(image_tag, repo_digests, image_id)
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

    def audit_stack_logs(self, stack_name: str, db: Optional[Session] = None) -> Dict[str, Any]:
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
                    "error_count": 0,
                    "containers_checked": 0,
                    "summary": f"No containers found for stack '{stack_name}'.",
                }

            container_errors: Dict[str, List[str]] = {}
            total_error_count = 0

            for c in stack_containers:
                c_name = getattr(c, "name", "") or getattr(c, "id", "unknown")
                try:
                    raw_logs = c.logs(tail=500)
                    if isinstance(raw_logs, bytes):
                        log_text = raw_logs.decode("utf-8", errors="replace")
                    else:
                        log_text = str(raw_logs)

                    matched_lines = []
                    for line in log_text.splitlines():
                        if ERROR_LOG_PATTERNS.search(line):
                            matched_lines.append(line.strip())

                    if matched_lines:
                        container_errors[c_name] = matched_lines
                        total_error_count += len(matched_lines)
                except Exception as log_err:
                    logger.warning(f"Failed to fetch logs for container '{c_name}': {log_err}")

            if total_error_count == 0:
                summary = f"Stack '{stack_name}' is healthy. No critical errors detected across {len(stack_containers)} container(s)."
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

            prompt = (
                f"You are an SRE bot reviewing daily container error logs for Docker stack '{stack_name}'.\n"
                f"The following error/warning lines were detected:\n\n{aggregated_errors}\n\n"
                "Analyze the errors and determine if there is an actionable root cause requiring human intervention or remediation. "
                "Output ONLY valid JSON with exactly four keys: "
                "'root_cause' (string explaining the issue), "
                "'proposed_fix' (string containing valid bash commands or remediation steps), "
                "'category' (string classifying the issue into one of: 'network', 'reverse_proxy', 'permissions', 'settings', 'database', 'unknown'), and "
                "'action_required' (boolean: true if actionable issue requiring fix/investigation, false if benign/informational/transient warning). "
                "Do not include markdown formatting or backticks."
            )

            ai_output = call_sre_ai_analyst(prompt)
            root_cause = "Container errors detected during daily SRE audit."
            proposed_fix = ""
            category = "unknown"
            action_required = True

            if ai_output:
                try:
                    json_match = re.search(r"\{.*\}", ai_output, re.DOTALL)
                    if json_match:
                        parsed = json.loads(json_match.group(0))
                        root_cause = parsed.get("root_cause", root_cause)
                        proposed_fix = parsed.get("proposed_fix", proposed_fix)
                        category = parsed.get("category", category)
                        action_required = bool(parsed.get("action_required", True))
                except Exception as parse_e:
                    logger.warning(f"Failed to parse AI output for stack '{stack_name}': {parse_e}")

            if action_required:
                primary_target_id = list(container_errors.keys())[0] if container_errors else stack_name

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

                audit = StackAudit(
                    id=str(uuid.uuid4()),
                    stack_name=stack_name,
                    status="ACTION_REQUIRED",
                    summary=root_cause,
                    error_count=str(total_error_count),
                    containers_checked=str(len(stack_containers)),
                    created_at=datetime.utcnow(),
                )
                db.add(audit)
                db.commit()

                # Trigger notification
                try:
                    from app.notifier import send_incident_notification
                    send_incident_notification(incident.id)
                except Exception as notif_err:
                    logger.error(f"Failed to send incident notification for SRE audit {incident.id}: {notif_err}")

                return {
                    "stack_name": stack_name,
                    "status": "ACTION_REQUIRED",
                    "incident_id": incident.id,
                    "error_count": total_error_count,
                    "containers_checked": len(stack_containers),
                    "root_cause": root_cause,
                    "proposed_fix": proposed_fix,
                    "category": category,
                    "summary": root_cause,
                }
            else:
                audit = StackAudit(
                    id=str(uuid.uuid4()),
                    stack_name=stack_name,
                    status="WARNING",
                    summary=root_cause or "Non-actionable / transient warnings detected.",
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
                    "error_count": total_error_count,
                    "containers_checked": len(stack_containers),
                    "summary": root_cause,
                    "root_cause": root_cause,
                }

        finally:
            if close_db_on_exit:
                db.close()

    def audit_all_stacks(self) -> List[Dict[str, Any]]:
        """
        Audits logs across all discovered Docker Compose stacks on the host.
        """
        stacks = self.discover_stacks()
        results = []
        for stack in stacks:
            stack_name = stack["name"]
            try:
                res = self.audit_stack_logs(stack_name)
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
        return results


# Global singleton instance
stack_watcher_manager = StackWatcherManager()

