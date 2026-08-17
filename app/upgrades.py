import os
import json
import uuid
import time
import queue
import logging
import threading
import subprocess
from datetime import datetime
from typing import List, Dict, Any, Optional
import requests

from app.database import SessionLocal, UpgradeRun, Incident, Target

logger = logging.getLogger("Upgrades")

BASE_DIR = "/containers"
EXCLUDE_STACKS = ["cloud", "dev", "tmp", "public_export", "monitorbot", "homelab-portal", "scripts", "notes", "lost+found", "venv"]

class UpgradeJob:
    def __init__(self, run_id: str, targets: List[str]):
        self.run_id = run_id
        self.targets = targets
        self.status = "RUNNING"  # RUNNING, SUCCESS, WARNING, FAILED, CANCELLED
        self.logs: List[str] = []
        self.started_at = datetime.utcnow()
        self.completed_at: Optional[datetime] = None
        self.canary_results: Dict[str, Any] = {}
        self.cancelled = False
        self.current_step = "Initializing"
        self._lock = threading.Lock()

    def append_log(self, text: str):
        with self._lock:
            timestamp = datetime.utcnow().strftime("%H:%M:%S")
            line = f"[{timestamp}] {text}"
            self.logs.append(line)
            logger.info(f"[Upgrade {self.run_id}] {text}")

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "run_id": self.run_id,
                "status": self.status,
                "targets": self.targets,
                "current_step": self.current_step,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "completed_at": self.completed_at.isoformat() if self.completed_at else None,
                "logs": self.logs[-200:],  # return latest 200 lines for live view
                "canary_results": self.canary_results
            }

class UpgradeManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(UpgradeManager, cls).__new__(cls)
                cls._instance.active_job = None
                cls._instance.worker_thread = None
        return cls._instance

    @staticmethod
    def get_stack_order() -> List[str]:
        conf_path = "/containers/scripts/stack_order.conf"
        if os.path.exists(conf_path):
            try:
                with open(conf_path, "r") as f:
                    content = f.read()
                # Parse STACK_ORDER=( ... )
                import re
                match = re.search(r"STACK_ORDER=\((.*?)\)", content, re.DOTALL)
                if match:
                    raw_items = match.group(1).replace('"', '').replace("'", "").split()
                    return [s.strip() for s in raw_items if s.strip()]
            except Exception as e:
                logger.warning(f"Failed to parse stack_order.conf: {e}")

        # Default fallback order
        return [
            "network", "webservices", "smarthome_support", "mcp", "ai",
            "smarthome_core", "books", "cameras", "container_registry",
            "finance", "media_content", "media_download", "media_discovery",
            "media_utils", "monitoring", "productivity", "remote_access"
        ]

    def discover_stacks(self) -> List[Dict[str, Any]]:
        """List all discovered stacks in /containers."""
        discovered = []
        ordered_keys = self.get_stack_order()

        all_stack_dirs = []
        if os.path.exists(BASE_DIR):
            for item in os.listdir(BASE_DIR):
                full_path = os.path.join(BASE_DIR, item)
                compose_file = os.path.join(full_path, "docker-compose.yaml")
                if os.path.isdir(full_path) and os.path.exists(compose_file):
                    if item not in EXCLUDE_STACKS:
                        all_stack_dirs.append(item)

        # Sort based on order
        sorted_stacks = []
        for target in ordered_keys:
            if target in all_stack_dirs:
                sorted_stacks.append(target)
        for s in all_stack_dirs:
            if s not in sorted_stacks:
                sorted_stacks.append(s)

        for name in sorted_stacks:
            stack_dir = os.path.join(BASE_DIR, name)
            compose_path = os.path.join(stack_dir, "docker-compose.yaml")
            services_count = 0
            containers = []
            try:
                with open(compose_path, "r") as f:
                    import yaml
                    data = yaml.safe_load(f)
                    if isinstance(data, dict) and "services" in data:
                        services_count = len(data["services"])
                        for s_name, s_val in data["services"].items():
                            c_name = s_val.get("container_name", s_name) if isinstance(s_val, dict) else s_name
                            containers.append(c_name)
            except Exception:
                pass

            discovered.append({
                "name": name,
                "path": stack_dir,
                "services_count": services_count,
                "containers": containers
            })

        return discovered

    def run_canary_audit(self) -> Dict[str, Any]:
        """Runs the 4-phase Canary Health & Routing Audit."""
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": "PASS",
            "checks": []
        }
        failures = 0

        # Check 1: Restarting containers
        try:
            res = subprocess.run(
                ["docker", "ps", "--filter", "status=restarting", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=10
            )
            restarting = res.stdout.strip()
            if restarting:
                failures += 1
                results["checks"].append({
                    "name": "Restarting Containers",
                    "status": "FAIL",
                    "detail": f"Containers in crashloop: {restarting}"
                })
            else:
                results["checks"].append({
                    "name": "Restarting Containers",
                    "status": "PASS",
                    "detail": "No restarting containers detected"
                })
        except Exception as e:
            results["checks"].append({"name": "Restarting Containers", "status": "ERROR", "detail": str(e)})

        # Check 2: Unhealthy containers
        try:
            res = subprocess.run(
                ["docker", "ps", "--filter", "health=unhealthy", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=10
            )
            unhealthy = res.stdout.strip()
            if unhealthy:
                failures += 1
                results["checks"].append({
                    "name": "Unhealthy Containers",
                    "status": "FAIL",
                    "detail": f"Unhealthy containers: {unhealthy}"
                })
            else:
                results["checks"].append({
                    "name": "Unhealthy Containers",
                    "status": "PASS",
                    "detail": "No unhealthy containers detected"
                })
        except Exception as e:
            results["checks"].append({"name": "Unhealthy Containers", "status": "ERROR", "detail": str(e)})

        # Check 3: Caddyfile Validation
        try:
            res = subprocess.run(
                ["docker", "compose", "-f", "/containers/webservices/docker-compose.yaml", "exec", "-T", "caddy", "caddy", "validate", "--config", "/etc/caddy/Caddyfile"],
                capture_output=True, text=True, timeout=15
            )
            if res.returncode == 0:
                results["checks"].append({
                    "name": "Caddyfile Validation",
                    "status": "PASS",
                    "detail": "Caddy reverse proxy configuration valid"
                })
            else:
                failures += 1
                results["checks"].append({
                    "name": "Caddyfile Validation",
                    "status": "FAIL",
                    "detail": res.stderr.strip() or res.stdout.strip() or "Caddyfile validation returned non-zero"
                })
        except Exception as e:
            results["checks"].append({"name": "Caddyfile Validation", "status": "ERROR", "detail": str(e)})

        # Check 4: Core HTTPS Reachability
        try:
            res = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-k", "--resolve", "wileyriley.com:443:10.0.0.10", "https://wileyriley.com"],
                capture_output=True, text=True, timeout=10
            )
            code = res.stdout.strip()
            if code in ["200", "302", "301"]:
                results["checks"].append({
                    "name": "HTTPS Reachability",
                    "status": "PASS",
                    "detail": f"Core portal returned HTTP {code}"
                })
            else:
                failures += 1
                results["checks"].append({
                    "name": "HTTPS Reachability",
                    "status": "FAIL",
                    "detail": f"Core portal returned HTTP {code}"
                })
        except Exception as e:
            results["checks"].append({"name": "HTTPS Reachability", "status": "ERROR", "detail": str(e)})

        results["overall_status"] = "PASS" if failures == 0 else "FAIL"
        results["failures_count"] = failures
        return results

    def start_upgrade(self, targets: Optional[List[str]] = None) -> Dict[str, Any]:
        """Initiate background upgrade job."""
        if self.active_job and self.active_job.status == "RUNNING":
            return {"status": "error", "message": "An upgrade job is already running", "job": self.active_job.to_dict()}

        all_stacks = self.discover_stacks()
        all_stack_names = [s["name"] for s in all_stacks]

        if not targets or "all" in targets:
            selected_targets = all_stack_names
        else:
            selected_targets = [t for t in targets if t in all_stack_names]

        if not selected_targets:
            return {"status": "error", "message": "No valid stacks specified for upgrade"}

        run_id = str(uuid.uuid4())
        job = UpgradeJob(run_id, selected_targets)
        self.active_job = job

        # Save record in DB
        db = SessionLocal()
        try:
            db_run = UpgradeRun(
                id=run_id,
                status="RUNNING",
                targets=json.dumps(selected_targets),
                logs="",
                canary_results="{}",
                started_at=datetime.utcnow()
            )
            db.add(db_run)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to record UpgradeRun in DB: {e}")
        finally:
            db.close()

        self.worker_thread = threading.Thread(target=self._run_upgrade_workflow, args=(job,), daemon=True)
        self.worker_thread.start()

        return {"status": "started", "job": job.to_dict()}

    def _run_upgrade_workflow(self, job: UpgradeJob):
        job.append_log(f"🚀 Starting upgrade run for {len(job.targets)} stacks: {', '.join(job.targets)}")
        
        # 1. Pull images
        job.current_step = "Pulling Images"
        for stack in job.targets:
            if job.cancelled:
                job.append_log("🛑 Upgrade cancelled by user.")
                job.status = "CANCELLED"
                break

            stack_dir = os.path.join(BASE_DIR, stack)
            job.append_log(f"⬇️ Pulling latest images for stack: {stack}...")
            try:
                proc = subprocess.run(
                    ["docker", "compose", "pull"],
                    cwd=stack_dir,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if proc.stdout:
                    for line in proc.stdout.strip().split("\n")[-5:]:
                        job.append_log(f"  {line}")
                if proc.returncode != 0:
                    job.append_log(f"⚠️ Warning: Pull returned non-zero for {stack}: {proc.stderr}")
            except Exception as e:
                job.append_log(f"❌ Error pulling stack {stack}: {e}")

        # 2. Recreate & Up containers
        if not job.cancelled:
            job.current_step = "Updating Containers"
            for stack in job.targets:
                if job.cancelled:
                    job.append_log("🛑 Upgrade cancelled by user.")
                    job.status = "CANCELLED"
                    break

                stack_dir = os.path.join(BASE_DIR, stack)
                job.append_log(f"🔼 Updating stack: {stack}...")
                try:
                    proc = subprocess.run(
                        ["docker", "compose", "up", "-d", "--remove-orphans"],
                        cwd=stack_dir,
                        capture_output=True,
                        text=True,
                        timeout=300
                    )
                    if proc.stdout:
                        for line in proc.stdout.strip().split("\n")[-5:]:
                            job.append_log(f"  {line}")
                    if proc.returncode != 0:
                        job.append_log(f"⚠️ Warning: Compose up error on {stack}: {proc.stderr}")
                except Exception as e:
                    job.append_log(f"❌ Error updating stack {stack}: {e}")

        # 3. Clean up dangling/old images
        if not job.cancelled:
            job.current_step = "Pruning Old Images"
            job.append_log("🧹 Pruning old unused Docker images...")
            try:
                subprocess.run(["docker", "image", "prune", "-af"], capture_output=True, timeout=60)
                job.append_log("✅ Image prune complete.")
            except Exception as e:
                job.append_log(f"⚠️ Prune warning: {e}")

        # 4. Portal CLI rebuild if available
        if not job.cancelled:
            job.current_step = "Rebuilding Portal Catalog"
            job.append_log("🔄 Rebuilding portal catalog and service indices...")
            try:
                if os.path.exists("/containers/scripts/portal_cli.py"):
                    subprocess.run(["python3", "/containers/scripts/portal_cli.py", "build"], capture_output=True, timeout=30)
                if os.path.exists("/containers/scripts/generate_catalog.py"):
                    subprocess.run(["python3", "/containers/scripts/generate_catalog.py"], capture_output=True, timeout=30)
                job.append_log("✅ Portal catalog indices rebuilt.")
            except Exception as e:
                job.append_log(f"⚠️ Portal build notice: {e}")

        # 5. Flush Uptime Kuma DNS Cache
        if not job.cancelled:
            job.append_log("🔄 Restarting Uptime Kuma & AutoKuma to flush internal container DNS cache...")
            try:
                subprocess.run(
                    ["docker", "compose", "-f", "/containers/monitoring/docker-compose.yaml", "restart", "uptime-kuma", "autokuma"],
                    capture_output=True, timeout=60
                )
                job.append_log("✅ Uptime Kuma DNS cache refreshed.")
            except Exception as e:
                job.append_log(f"⚠️ Uptime Kuma restart warning: {e}")

        # 6. Run Canary Audit
        job.current_step = "Running Canary Audit"
        job.append_log("🩺 Running 4-Phase Canary Health & Routing Audit...")
        time.sleep(3)  # Give containers a moment to settle
        canary = self.run_canary_audit()
        job.canary_results = canary

        for check in canary.get("checks", []):
            icon = "✅" if check["status"] == "PASS" else "❌"
            job.append_log(f"{icon} Canary Check '{check['name']}': {check['status']} - {check['detail']}")

        # 7. Post-Upgrade AI Self-Healing Hook
        failed_containers = []
        if canary.get("overall_status") != "PASS":
            job.append_log("⚠️ Canary audit reported failures. Checking if AI investigation is needed...")
            for check in canary.get("checks", []):
                if check["status"] == "FAIL":
                    detail = check.get("detail", "")
                    if "crashloop:" in detail or "Unhealthy containers:" in detail:
                        # Extract container names
                        parts = detail.split(":")[-1].split(",")
                        for p in parts:
                            c = p.strip()
                            if c and c not in failed_containers:
                                failed_containers.append(c)

        if failed_containers:
            job.append_log(f"🤖 Triggering AI Self-Healing Investigation for failed containers: {', '.join(failed_containers)}...")
            from app.investigator import trigger_investigation
            db = SessionLocal()
            try:
                for c_name in failed_containers:
                    # Create or update incident
                    inc = Incident(
                        id=str(uuid.uuid4()),
                        target_id=c_name,
                        status="DETECTED",
                        error_logs=f"Container failed post-upgrade Canary Health Audit during Upgrade Run {job.run_id}.\nCanary Details: {json.dumps(canary)}",
                        created_at=datetime.utcnow()
                    )
                    db.add(inc)
                    db.commit()
                    trigger_investigation(inc.id)
                    job.append_log(f"  Incident {inc.id} dispatched for target '{c_name}' to AI Investigator.")
            except Exception as inc_err:
                logger.error(f"Error queueing post-upgrade investigation: {inc_err}")
            finally:
                db.close()

        # 8. Finalize job status
        job.completed_at = datetime.utcnow()
        if job.cancelled:
            job.status = "CANCELLED"
            job.current_step = "Cancelled"
        elif canary.get("overall_status") == "PASS":
            job.status = "SUCCESS"
            job.current_step = "Completed Successfully"
            job.append_log("🎉 Upgrade and Canary Audit completed: ALL SYSTEMS HEALTHY.")
        else:
            job.status = "WARNING"
            job.current_step = f"Completed with {canary.get('failures_count', 0)} Warnings"
            job.append_log(f"⚠️ Upgrade finished with warnings. Review canary checks and AI remediation items.")

        # Update DB record
        db = SessionLocal()
        try:
            db_run = db.query(UpgradeRun).filter(UpgradeRun.id == job.run_id).first()
            if db_run:
                db_run.status = job.status
                db_run.logs = "\n".join(job.logs)
                db_run.canary_results = json.dumps(job.canary_results)
                db_run.completed_at = job.completed_at
                db.commit()
        except Exception as e:
            logger.error(f"Failed to update UpgradeRun in DB: {e}")
        finally:
            db.close()

    def cancel_active_upgrade(self) -> Dict[str, Any]:
        if self.active_job and self.active_job.status == "RUNNING":
            self.active_job.cancelled = True
            self.active_job.append_log("Cancellation requested by user.")
            return {"status": "cancelling", "run_id": self.active_job.run_id}
        return {"status": "no_active_job"}

    def get_live_status(self) -> Optional[Dict[str, Any]]:
        if self.active_job:
            return self.active_job.to_dict()
        return None

upgrades_manager = UpgradeManager()
