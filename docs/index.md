---
layout: home

hero:
  name: "MonitorBot"
  text: "Autonomous Homelab SRE"
  tagline: "Self-Healing Watcher & AI Agent Delegation"
  actions:
    - theme: brand
      text: Architecture
      link: /architecture/overview
    - theme: alt
      text: API Reference
      link: /reference/api

features:
  - title: Autonomous SRE
    details: Proactive container event watching, scheduled log auditing, and automatic incident generation.
  - title: AI Agent Delegation
    details: Dispatches root-cause analysis via CLIAgentDispatch HTTP with automatic OpenCode/Antigravity CLI failover.
  - title: Resilient Reliability
    details: Dual-path notifications (LAN fallback) and proactive FUSE mount health audits.
---

## Overview Workflow

```mermaid
flowchart LR
    Docker[Docker Engine] -->|Events / Logs| Watcher[Event Watcher]
    Watcher -->|Incident Detected| Auditor[SRE Auditor]
    Auditor -->|RCA Prompt| Dispatch[CLIAgentDispatch HTTP]
    Dispatch -->|Fallbacks| CLI[OpenCode / AGY CLI]
    Dispatch -->|Remediation Proposal| Notifier[ntfy / Host Webhook]
```
