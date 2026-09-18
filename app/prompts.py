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
2. Stack Root Paths: All Docker Compose stacks are located in '/containers/<category>/docker-compose.yaml'. Shared networks are registered in '/containers/networks-compose.yaml'.
3. Reverse Proxy (Caddy): Caddy is the universal reverse proxy. EXPLICIT CADDYFILE ONLY: All persistent service routes MUST be explicitly configured in '/containers/webservices/caddy/Caddyfile' for determinism and reliability. DO NOT use 'caddy-docker-proxy' labels ('caddy=...', 'caddy.reverse_proxy=...') in compose files. Ephemeral previews and dev backends use 'agent-preview' or dynamic bridge 'https://p-<port>.wileyriley.com'. NOTE: Nginx / SWAG is deprecated and NOT used. NEVER generate Nginx directives (such as 'proxy_buffering', 'proxy_read_timeout', 'proxy_pass', etc.) or search deprecated Nginx paths. Before restarting Caddy, validate with: docker compose exec caddy caddy fmt --overwrite /etc/caddy/Caddyfile && docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile.
4. Authentication & SSO: TinyAuth ('tinyauth.apps.*' labels) and PocketID provide forward-auth and OIDC. Servarr apps (Radarr, Sonarr, Prowlarr) use External authentication behind TinyAuth.
5. Local DNS: AdGuard Home at 10.0.0.2 (pi@adguard). New local rewrites use '/home/pi/scripts/adguard-add-rewrite.sh <domain> 10.0.0.10'. Public wildcard is '*.wileyriley.com' managed via Cloudflare.
6. MCP Router & Knowledge Hub:
   - MCP Gateway Router: http://10.0.0.10:8026/sse (X-App-Key: mcp-global-steve-default-cli-key-99)
   - Knowledge / Notes RAG (ContextCortex): Direct fallback at http://10.0.0.10:8021/sse if router is unavailable.
7. Container Immutability & Deployment:
   - NEVER hot-patch or replace files inside running containers (no 'docker cp' or live file editing).
   - Containers are immutable runtime artifacts. Always deploy using official/built images followed by: docker compose up -d --force-recreate <service>.
8. Storage & Disk SMART Context:
   - High-capacity, long-running SATA drives (e.g. /dev/sdg on /drives/moviestv4k) may have historical UDMA CRC error records from past cable issues that cause smartctl to exit with code 64 (bit 6: 'The device error log contains records of errors'). This does NOT indicate active drive degradation.
   - A drive is only degraded or failing if 'SMART overall-health self-assessment' FAILS or raw values for Reallocated_Sector_Ct (ID 5), Current_Pending_Sector (ID 197), or Offline_Uncorrectable (ID 198) are actively incrementing. Do NOT recommend drive replacement on historical error logs alone.
9. Transient Job Retries & Self-Healing:
   - Background cron jobs (e.g., 'cron-automations', budget sync) employ retry loops. Transient retry notices (e.g., '[RETRY] ... Attempt 1/3') are normal self-healing behavior and do NOT represent fatal failures or require credential re-authentication unless all retry attempts are exhausted.
10. Container Healthchecks & DB Noise:
    - Certain database containers (e.g. MariaDB in 'finance' / 'receiptwrangler_db') execute periodic local healthchecks (such as 'mysqladmin ping') that log benign access denied or password warnings during routine polling. Verify whether connection errors match container healthcheck intervals before diagnosing broken credentials.
11. Media Scanners & Idempotent Rescans:
    - Media management services (Seerr, ErsatzTV, Radarr) perform routine background rescans. Handled unique constraint catches (e.g. Seerr Plex scan duplicate tvdbId) and duplicate file notices ('Media file already exists') are non-fatal application-level deduplication, not database corruption.
12. Optional Feature Warnings:
    - Services with unconfigured optional modules (such as Sure's 'ImportMarketDataJob' when no market quote provider is configured) emit continuous informational warnings that are benign by design and do not require remediation.
"""

BENIGN_LOG_GUIDELINES = """
=== Benign Homelab Noise & False-Positive Guidelines ===
Mark 'action_required': false (and state benign in 'root_cause') for any of the following normal homelab events:
- TinyAuth 401s: 'status=401' on '/api/auth/' or client auth checks (normal unauthenticated browser/crawler requests before user login).
- OpenIddict / MCP Probes: Unauthenticated 401 challenge logs during token negotiation.
- MCP SSE Reconnects: Transient SSE stream closes with 'idle connection timeout (normal)' in LibreChat, OpenCode, or MCP clients.
- Proxied Internal Services: Warnings about running without internal basic auth or TLS (e.g. Glances, Portainer) when they are intentionally protected behind TinyAuth and Caddy.
- Sleeping / Standby IoT & Media Devices: Connection timeouts to smart TVs (e.g. Android TV at 10.0.0.230, Apple TV/HomeKit at 10.0.0.39) or battery sensors in Home Assistant / ESPHome when the device is powered off.
- Terminal / SSH Disconnects: Web terminal or SSH client disconnects ('ECONNRESET', 'SIGPIPE' in Termix, Guacamole, Code-Server) when users close browser tabs.
- Local Custom Images in WUD: Whats-Up-Docker logging '404 NAME_UNKNOWN' for locally built images (e.g. custom dev or pipeline containers) not hosted on Docker Hub.
- Transient DB Startup Synchronization: Application containers logging 'FATAL: the database system is starting up' during initial container boot before Postgres/MySQL is ready.
- Deprecation Notices: Informational deprecation warnings (e.g. MySQL 'mysql_native_password', Node deprecation warnings).
- External Scraper Rate Limits: Search engine 403s or CAPTCHA challenges in SearXNG from public rate limits.
"""

REMEDIATION_PLAN_CONTRACT = """
=== Remediation Plan Contract ===
- 'proposed_fix' may be a single bash command OR a structured, multi-step remediation plan with sequential commands, compose commands, and verification steps.
- Always use exact, real paths (e.g., 'cd /containers/<stack> && docker compose restart <service>').
- Do NOT use placeholder text (e.g., '<target-host-ip>', 'example.com', '<id>').
- CRITICAL GUARDRAIL: NEVER generate raw SQL 'DELETE', 'DROP', or 'UPDATE' commands on application SQLite or PostgreSQL databases (e.g., Seerr, Plex, Home Assistant DBs) to fix metadata or scraping errors. Application databases must only be managed via their official web UIs or container restarts.
- CRITICAL GUARDRAIL: NEVER edit compose files using brittle regex/sed commands (e.g., modifying auth flags via sed). Use clean docker compose restart/pull or proper manual configuration instructions.
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
        f"Here are the extracted warning and error logs grouped by container:\n"
        f"{aggregated_errors}\n\n"
        "Evaluate each container independently. Provide your diagnosis as strict JSON matching this schema:\n"
        "{\n"
        '  "containers": {\n'
        '    "<container_name>": {\n'
        '      "root_cause": "Specific root cause for this container (1-2 sentences)",\n'
        '      "proposed_fix": "Clear, actionable step-by-step remediation commands",\n'
        '      "category": "one of: network_error, database_error, auth_failure, storage_io, api_error, config_syntax, resource_limit, transient_warning",\n'
        '      "action_required": true or false\n'
        "    }\n"
        "  },\n"
        '  "overall_summary": "1-2 sentence summary of overall stack health"\n'
        "}\n"
        "Do not include markdown formatting or backticks."
    )

