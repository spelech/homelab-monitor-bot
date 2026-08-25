"""
Prompt engineering and homelab infrastructure context provider for SRE MonitorBot.
Enriches AI investigator and daily SRE audit prompts with ground-truth Docker stack metadata,
homelab architecture conventions, benign noise rules, and multi-step plan contracts.
"""

import os
import json
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("Prompts")

HOMELAB_SYSTEM_RULES = """
=== Homelab Infrastructure Architecture & Rules ===
1. Server Host IP: 10.0.0.10 (Linux host running Docker Compose & systemd).
2. Stack Root Paths: All Docker Compose stacks are located in '/containers/<category>/docker-compose.yaml'.
3. Reverse Proxy: Caddy is the universal reverse proxy. Dynamic routes are managed via container labels ('caddy=...'), and static routes live in '/containers/webservices/caddy/Caddyfile'. NOTE: Nginx / SWAG is deprecated and NOT used.
4. Authentication & SSO: TinyAuth ('tinyauth.apps.*' labels) and PocketID provide forward-auth and OIDC.
5. Local DNS: AdGuard Home at 10.0.0.2 (pi@adguard). Public wildcard is '*.wileyriley.com'.
6. MCP Router & Knowledge Hub:
   - MCP Gateway Router: http://10.0.0.10:8026/sse (X-App-Key: mcp-global-steve-default-cli-key-99)
   - Knowledge / Notes RAG (ContextCortex): Direct fallback at http://10.0.0.10:8021/sse if router is unavailable.
"""

BENIGN_LOG_GUIDELINES = """
=== Benign Homelab Noise & False-Positive Guidelines ===
Mark 'action_required': false (and state benign in 'root_cause') for any of the following normal homelab events:
- TinyAuth 401s: 'status=401' on '/api/auth/' or client auth checks (normal unauthenticated browser/crawler requests before user login).
- Proxied Internal Services: Warnings about running without internal basic auth or TLS (e.g. Glances, Portainer) when they are intentionally protected behind TinyAuth and Caddy.
- Sleeping / Standby IoT & Media Devices: Connection timeouts to smart TVs (e.g. Android TV at 10.0.0.230, Apple TV/HomeKit at 10.0.0.39) or battery sensors in Home Assistant / ESPHome when the device is powered off.
- Terminal / SSH Disconnects: Web terminal or SSH client disconnects ('ECONNRESET', 'SIGPIPE' in Termix, Guacamole, Code-Server) when users close browser tabs.
- Local Custom Images in WUD: Whats-Up-Docker logging '404 NAME_UNKNOWN' for locally built images (e.g. custom dev or pipeline containers) not hosted on Docker Hub.
- Transient DB Startup Synchronization: Application containers logging 'FATAL: the database system is starting up' during initial container boot before Postgres/MySQL is ready.
- Deprecation Notices: Informational deprecation warnings (e.g. MySQL 'mysql_native_password', Node deprecation warnings).
"""

REMEDIATION_PLAN_CONTRACT = """
=== Remediation Plan Contract ===
- 'proposed_fix' may be a single bash command OR a structured, multi-step remediation plan with sequential commands, compose commands, and verification steps.
- Always use exact, real paths (e.g., 'cd /containers/<stack> && docker compose restart <service>').
- Do NOT use placeholder text (e.g., '<target-host-ip>', 'example.com', '<id>').
- Do NOT output markdown formatting, backticks, or fences in the raw JSON keys.
"""


def get_stack_docker_context(stack_name: str) -> str:
    """Extracts live stack metadata directly from the Docker daemon socket."""
    try:
        import docker
        client = docker.from_env()
        containers = client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={stack_name}"}
        )
        if not containers:
            return f"Stack '{stack_name}': No active containers found under compose project label."

        working_dir = None
        config_files = None
        container_summaries = []

        for c in containers:
            labels = c.attrs.get("Config", {}).get("Labels", {})
            if not working_dir:
                working_dir = labels.get("com.docker.compose.project.working_dir")
            if not config_files:
                config_files = labels.get("com.docker.compose.project.config_files")

            name = c.name
            status = c.status
            health = c.attrs.get("State", {}).get("Health", {}).get("Status", "none")
            image = c.attrs.get("Config", {}).get("Image", "")
            
            ports_dict = c.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
            mapped_ports = []
            for p, bindings in ports_dict.items():
                if bindings:
                    for b in bindings:
                        mapped_ports.append(f"{b.get('HostPort')}->{p}")

            port_str = ", ".join(mapped_ports) if mapped_ports else "none"
            container_summaries.append(
                f"  - Container: '{name}' | Status: {status} (Health: {health}) | Image: {image} | Ports: {port_str}"
            )

        compose_file_path = config_files or (f"{working_dir}/docker-compose.yaml" if working_dir else f"/containers/{stack_name}/docker-compose.yaml")
        summary_text = (
            f"=== Live Stack Ground Truth: '{stack_name}' ===\n"
            f"Compose File: {compose_file_path}\n"
            f"Stack Containers ({len(container_summaries)}):\n" + "\n".join(container_summaries)
        )
        return summary_text
    except Exception as e:
        logger.debug(f"Failed to extract Docker stack context for '{stack_name}': {e}")
        return f"Stack '{stack_name}': Working dir default '/containers/{stack_name}/docker-compose.yaml'"


def get_container_docker_context(container_name: str) -> str:
    """Extracts live container metadata directly from the Docker daemon socket."""
    try:
        import docker
        client = docker.from_env()
        c = client.containers.get(container_name)
        labels = c.attrs.get("Config", {}).get("Labels", {})
        project = labels.get("com.docker.compose.project", "unknown")
        working_dir = labels.get("com.docker.compose.project.working_dir", f"/containers/{project}")
        config_files = labels.get("com.docker.compose.project.config_files", f"{working_dir}/docker-compose.yaml")
        
        status = c.status
        health = c.attrs.get("State", {}).get("Health", {}).get("Status", "none")
        image = c.attrs.get("Config", {}).get("Image", "")

        return (
            f"=== Live Container Ground Truth: '{container_name}' ===\n"
            f"Stack Name: {project}\n"
            f"Compose File: {config_files}\n"
            f"Status: {status} (Health: {health})\n"
            f"Image: {image}\n"
        )
    except Exception as e:
        logger.debug(f"Failed to extract Docker container context for '{container_name}': {e}")
        return f"Container '{container_name}': Ground truth lookup unavailable."


def build_investigator_prompt(
    target_id: str,
    error_logs: str,
    historical_context: str = "",
    is_systemd: bool = False
) -> str:
    """Constructs enriched prompt for reactive incident investigation."""
    context_noun = "systemd service" if is_systemd else "container"
    ground_truth = (
        f"=== Systemd Target: '{target_id}' ===\nService: {target_id}.service on host 10.0.0.10"
        if is_systemd else get_container_docker_context(target_id)
    )

    return (
        f"{HOMELAB_SYSTEM_RULES}\n\n"
        f"{ground_truth}\n\n"
        f"{BENIGN_LOG_GUIDELINES}\n\n"
        f"{REMEDIATION_PLAN_CONTRACT}\n\n"
        f"=== Incident Details ===\n"
        f"Failure detected on {context_noun} '{target_id}'.\n"
        f"Error Logs:\n{error_logs}{historical_context}\n\n"
        "You are an SRE bot. Focus strictly on diagnosing this issue by inspecting the provided ground-truth configuration and logs. "
        "Do NOT research, grep, or search for the 'agy' command or its flags (like --dangerously-skip-permissions) on the system. "
        "Output ONLY valid JSON with exactly three keys: "
        "'root_cause' (a string explaining the issue), "
        "'proposed_fix' (a string containing valid bash commands or a multi-step remediation plan), and "
        "'category' (a string classifying the issue into one of: 'network', 'reverse_proxy', 'permissions', 'settings', 'database', 'unknown'). "
        "Do not include markdown formatting or backticks."
    )


def build_sre_audit_prompt(stack_name: str, aggregated_errors: str) -> str:
    """Constructs enriched prompt for daily SRE stack log audits."""
    ground_truth = get_stack_docker_context(stack_name)

    return (
        f"{HOMELAB_SYSTEM_RULES}\n\n"
        f"{ground_truth}\n\n"
        f"{BENIGN_LOG_GUIDELINES}\n\n"
        f"{REMEDIATION_PLAN_CONTRACT}\n\n"
        f"=== Daily SRE Log Audit for Stack: '{stack_name}' ===\n"
        f"The following error/warning lines were detected:\n\n{aggregated_errors}\n\n"
        "Analyze the errors against the homelab rules and benign noise guidelines. "
        "Determine if there is an actionable root cause requiring human intervention or remediation. "
        "Output ONLY valid JSON with exactly four keys: "
        "'root_cause' (string explaining the issue), "
        "'proposed_fix' (string containing valid bash commands or a multi-step remediation plan), "
        "'category' (string classifying the issue into one of: 'network', 'reverse_proxy', 'permissions', 'settings', 'database', 'unknown'), and "
        "'action_required' (boolean: true if actionable issue requiring fix/investigation, false if benign/informational/transient warning). "
        "Do not include markdown formatting or backticks."
    )
