---
layout: home

hero:
  name: "MonitorBot"
  text: "Autonomous Homelab SRE"
  tagline: "Event-driven watcher, self-healing AI investigator & Canary health auditor"
  actions:
    - theme: brand
      text: Architecture Overview
      link: /architecture/overview
    - theme: alt
      text: Event Watcher
      link: /architecture/event-watcher
    - theme: alt
      text: SRE Auditor
      link: /architecture/sre-auditor

features:
  - title: "Event-Driven Docker Watcher"
    details: "Sub-second container crash triage via real-time Docker socket stream listening, with intelligent noise suppression for graceful SIGTERM exits and maintenance windows."
  - title: "AI Delegation Gateway"
    details: "Multi-tiered AI investigation bridging CLIAgentDispatch HTTP (:8032), headless OpenCode daemon (:4096), and local Antigravity (agy) CLI subprocesses."
  - title: "Proactive SRE Audits"
    details: "Automated 24-hour log auditing across all Docker Compose stacks, per-container incident granularity, and 4-phase canary upgrade health verification."
  - title: "FUSE Mount Health Auditor"
    details: "Proactive 10-minute thread-isolated probing of rclone, mergerfs, and NFS storage mounts with strict timeouts to prevent unkillable kernel D-state hangs."
  - title: "Fail-Safe Notifications"
    details: "Real-time incident alerts with actionable HTTP buttons via ntfy, automatic local LAN IP rewrites for network isolation, and immediate SMTP email fallback."
  - title: "FastMCP Server"
    details: "Native Model Context Gateway integration exposing SSE endpoints for autonomous tool execution, stack inspection, and remediation actions."
---

## System Workflow & Lifecycle

MonitorBot orchestrates an autonomous feedback loop connecting real-time Docker engine events, scheduled SRE log auditing, AI-powered root cause analysis, and human-in-the-loop remediation.

```mermaid
flowchart TD
    subgraph Detection["1. Detection & Ingestion"]
        DockerSock["Docker Socket (/var/run/docker.sock)"] -->|Container Die / Unhealthy| Watcher["Event Watcher (app/watcher.py)"]
        CronTimer["Daily SRE Cron (03:00 UTC)"] -->|24h Log Scan| SREAuditor["SRE Auditor (app/stack_watcher.py)"]
        MountTimer["Storage Audit (Every 10m)"] -->|statvfs Probes| StorageAuditor["Storage Auditor (app/system_health.py)"]
    end

    subgraph Triage["2. Noise Filtering & Incident Creation"]
        Watcher -->|Filter Benign Exits / Noise| IncidentDB[("SQLite DB (monitorbot.db)")]
        SREAuditor -->|Per-Container Granularity| IncidentDB
        StorageAuditor -->|Hung Mount Detection| IncidentDB
    end

    subgraph Intelligence["3. AI Delegation Gateway"]
        IncidentDB -->|Trigger Investigation| InvQueue["Sequential FIFO Queue"]
        InvQueue --> Qdrant[("Qdrant Vector Memory\n(Historical Fixes)")]
        InvQueue --> Dispatcher{"AI Delegation Gateway"}
        Dispatcher -->|Primary HTTP :8032| CLIAgent["CLIAgentDispatch HTTP"]
        Dispatcher -->|Fallback HTTP :4096| OpenCode["OpenCode Serve Daemon"]
        Dispatcher -->|Fallback CLI Subprocess| AGYCLI["Antigravity CLI (agy)"]
    end

    subgraph Notification["4. Fail-Safe Alerting & Action"]
        Dispatcher -->|Parsed Diagnosis & Fix| Notifier["Notifier Engine (app/notifier.py)"]
        Notifier -->|Primary Alert + Action Buttons| NtfyCloud["ntfy (https://ntfy.wileyriley.com)"]
        Notifier -->|LAN Fallback| NtfyLAN["Local ntfy (http://localhost:9010)"]
        Notifier -->|SMTP Fallback| SMTPMail["Admin Email (SSL 465)"]
    end

    subgraph Remediation["5. Remediation & Continuous Learning"]
        NtfyCloud -->|Interactive Webhook Click| WebhookAPI["FastAPI Webhook (:9013)"]
        NtfyLAN -->|LAN Webhook Click| WebhookAPI
        WebhookAPI --> Remediator["Remediator (app/remediator.py)"]
        Remediator -->|Restart / Compose Up / Exec| DockerEngine["Docker Engine"]
        Remediator -->|Record Successful Vector| Qdrant
    end
```

## Core Architecture Matrix

| Capability | Component | Primary Mechanism | Fallback / Redundancy |
| :--- | :--- | :--- | :--- |
| **Reactive Crash Detection** | `app/watcher.py` | Sub-second Docker event stream listener | Circuit breaker (60m window, >=2 fails) |
| **Scheduled Log Auditing** | `app/stack_watcher.py` | 24-hour log scan across all compose stacks | Benign homelab regex filter |
| **AI Investigation** | `app/investigator.py` | `CLIAgentDispatch` HTTP (`:8032/v1`) | OpenCode daemon (`:4096`) & Antigravity `agy` CLI |
| **Memory & Learning** | `app/qdrant_mem.py` | Qdrant vector semantic search (`FastEmbed`) | Direct rule-based prompt synthesis |
| **Alert Dispatch** | `app/notifier.py` | Cloud ntfy with actionable HTTP buttons | Local LAN port (`:9010`) & SMTP TLS email |
| **Storage & Mount Health** | `app/system_health.py` | Thread-isolated `statvfs` with 3s timeout | Kernel D-state hang isolation |
| **Stack Upgrades** | `app/upgrades.py` | Ordered compose pull, recreate, prune | 4-Phase Canary Health & Routing Audit |
| **MCP Integration** | `app/routers/` | FastMCP SSE server for Model Context Gateway | REST API (`/api/incidents`, `/api/stacks`) |

## Quick Navigation

- **[System Architecture Overview](/architecture/overview)**: Deep dive into the process topology, SQLite schema, thread model, and runtime boundaries.
- **[Docker Event Watcher](/architecture/event-watcher)**: Real-time container event handling, debouncing, intelligent noise suppression, and circuit breakers.
- **[SRE Stack Auditor](/architecture/sre-auditor)**: Daily log audits, error burst detection, per-container incident granularity, and canary upgrades.
- **[AI Delegation Gateway](/ai/agent-dispatch)**: CLIAgentDispatch HTTP, OpenCode daemon, Antigravity CLI failover, and token telemetry.
- **[Fail-Safe Notifications](/reliability/notifications)**: Actionable ntfy buttons, local LAN IP rewrites, and immediate SMTP email fallbacks.
