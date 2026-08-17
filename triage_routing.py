#!/usr/bin/env python3
import os
import json
import re
import urllib.request
import urllib.error
import sys

DATA_JSON_PATH = "/containers/dev/caddy-auth-portal/data.json"
CADDYFILE_PATH = "/containers/webservices/caddy/Caddyfile"

def get_caddy_mappings():
    mappings = {}
    if not os.path.exists(CADDYFILE_PATH):
        return mappings
    
    current_domain = None
    depth = 0
    with open(CADDYFILE_PATH, "r") as f:
        for line in f:
            line = line.strip()
            
            open_braces = line.count("{")
            close_braces = line.count("}")
            
            # Match domain block start e.g. "riven.wileyriley.com {"
            domain_match = re.match(r"^([a-zA-Z0-9\.\-]+)\s*\{", line)
            if domain_match and depth == 0:
                current_domain = domain_match.group(1)
                depth = open_braces
                continue
                
            if current_domain:
                depth += open_braces - close_braces
                if depth <= 0:
                    current_domain = None
                    depth = 0
                    continue
                
                if "reverse_proxy" in line:
                    # Match reverse_proxy target e.g. "reverse_proxy riven:8080"
                    proxy_match = re.search(r"reverse_proxy\s+([a-zA-Z0-9\.\-_]+):(\d+)", line)
                    if proxy_match:
                        mappings.setdefault(current_domain, []).append({
                            "host": proxy_match.group(1),
                            "port": int(proxy_match.group(2))
                        })
    return mappings

def test_http_endpoint(port):
    url = f"http://localhost:{port}"
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status, resp.reason
    except urllib.error.HTTPError as e:
        return e.code, e.reason
    except Exception as e:
        return None, str(e)

def run_triage():
    print("# SRE Triage Report: Routing & Reverse Proxy Health")
    print(f"Analyzing `{DATA_JSON_PATH}` and `{CADDYFILE_PATH}`...\n")

    if not os.path.exists(DATA_JSON_PATH):
        print(f"Error: {DATA_JSON_PATH} does not exist.")
        sys.exit(1)

    with open(DATA_JSON_PATH, "r") as f:
        data = json.load(f)

    caddy_mappings = get_caddy_mappings()

    # Group containers by stack
    stacks = {}
    for item in data:
        stack = item.get("stack", "unknown")
        stacks.setdefault(stack, []).append(item)

    for stack_name, containers in sorted(stacks.items()):
        print(f"## Stack: `{stack_name}`")
        has_warnings = False
        findings = []

        # Find domains configured for this stack
        domain_to_containers = {}
        for c in containers:
            labels = c.get("labels", {})
            for key, val in labels.items():
                if key.endswith(".config.domain"):
                    domain_to_containers.setdefault(val, []).append(c)

        for domain, domain_containers in sorted(domain_to_containers.items()):
            caddy_targets = caddy_mappings.get(domain, [])
            print(f"\n### Domain: `https://{domain}`")
            if caddy_targets:
                targets_str = ", ".join([f"`{t['host']}:{t['port']}`" for t in caddy_targets])
                print(f"* **Caddy Targets**: {targets_str}")
            else:
                print(f"* **Caddy Targets**: *None (Not found in Caddyfile)*")

            # Check each container in this domain group
            for c in domain_containers:
                cname = c.get("container_name")
                ports = c.get("ports", [])
                
                for port_mapping in ports:
                    if ":" in port_mapping:
                        # Strip protocol suffixes like /tcp or /udp
                        clean_mapping = port_mapping.split("/")[0]
                        parts = clean_mapping.split(":")
                        if len(parts) >= 2:
                            host_str = parts[-2]
                            container_str = parts[-1]
                            # Extract numeric parts to handle env variables with defaults e.g. ${PORT:-8461}
                            host_digits = re.findall(r"\d+", host_str)
                            container_digits = re.findall(r"\d+", container_str)
                            if host_digits and container_digits:
                                host_port = int(host_digits[-1])
                                container_port = int(container_digits[-1])
                            else:
                                continue
                        else:
                            continue
                    else:
                        continue

                    status_code, reason = test_http_endpoint(host_port)
                    is_active = status_code is not None
                    
                    is_caddy_dest = False
                    matched_target = None
                    for caddy_target in caddy_targets:
                        if (caddy_target["host"] in [cname, c.get("service_name")]) and (caddy_target["port"] == container_port):
                            is_caddy_dest = True
                            matched_target = caddy_target
                            break

                    badge = "✅ ACTIVE" if is_active else "❌ OFFLINE"
                    print(f"  * Container `{cname}` (Host Port `{host_port}` -> `{container_port}`): {badge} (HTTP {status_code or 'Error'} {reason or ''})")
                    
                    if is_caddy_dest:
                        # Verify if caddy target returns 404/error, but there's a frontend in the same stack that is active
                        if is_active and status_code in [404, 500, 502, 503]:
                            # Look for other containers in the same stack that return 200 or 3xx redirect
                            for other in containers:
                                if other.get("container_name") != cname:
                                    for op in other.get("ports", []):
                                        if ":" in op:
                                            # Strip protocol suffixes and IP prefixes
                                            clean_op = op.split("/")[0]
                                            parts_op = clean_op.split(":")
                                            if len(parts_op) >= 2:
                                                ohp = int(parts_op[-2])
                                                ocp = int(parts_op[-1])
                                            else:
                                                continue
                                            o_status, o_reason = test_http_endpoint(ohp)
                                            if o_status and (o_status in [200, 301, 302, 307, 308]):
                                                # Check if this healthy target is already mapped
                                                already_mapped = False
                                                for t in caddy_targets:
                                                    if t["host"] in [other.get("container_name"), other.get("service_name")] and t["port"] == ocp:
                                                        already_mapped = True
                                                        break
                                                if not already_mapped:
                                                    warn_msg = (
                                                        f"⚠️ **ROUTING WARNING**: Caddy maps `https://{domain}` to `{cname}:{container_port}` (returns HTTP {status_code}), "
                                                        f"but container `{other.get('container_name')}:{ocp}` returns a healthy UI/redirect (HTTP {o_status}) and is NOT mapped! "
                                                        f"Should Caddy point to `{other.get('container_name')}:{ocp}` instead?"
                                                    )
                                                    findings.append(warn_msg)
                                                    has_warnings = True

        if has_warnings:
            print("\n#### Diagnostics:")
            for f in findings:
                print(f)
        else:
            print("\n*All routing checks for this stack passed.*")
        print("\n" + "-"*40)

if __name__ == "__main__":
    run_triage()
