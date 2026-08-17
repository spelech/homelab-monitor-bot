import os
import logging
import threading
from typing import List
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Query, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import init_db, get_db, Target, Incident, SessionLocal, get_setting, check_maintenance_status
from app.watcher import start_watcher_thread
from app.scheduler import start_scheduler
from app.remediator import run_remediation
from app.notifier import send_followup_notification

# Import modular routers
from app.routers import incidents, upgrades, settings, usage

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent

mcp_server = Server("monitorbot-mcp")
sse_transport = SseServerTransport("/messages/")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AutoHeal")

# Load environment configs
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "")
PORT = int(os.getenv("PORT", "9013"))
HOST = os.getenv("HOST", "0.0.0.0")

# Setup legacy Jinja2 templates directory
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    logger.info("Initializing AutoHeal Database...")
    init_db()

    # Reset any stuck active incidents from a previous run to FAILED
    db = SessionLocal()
    try:
        stuck_incidents = db.query(Incident).filter(
            Incident.status.in_(["DETECTED", "INVESTIGATING", "FIXING"])
        ).all()
        for inc in stuck_incidents:
            logger.warning(f"Resetting orphaned active incident {inc.id} ({inc.status}) to FAILED.")
            inc.status = "FAILED"
            inc.execution_log = f"System restarted or process terminated while in {inc.status} state."
            inc.completed_at = datetime.utcnow()
        db.commit()
    except Exception as reset_err:
        logger.error(f"Failed to reset orphaned incidents: {reset_err}")
        db.rollback()
    finally:
        db.close()
    
    logger.info("Starting Docker event watcher background worker...")
    start_watcher_thread()
    
    logger.info("Starting background APScheduler...")
    start_scheduler()
    
    logger.info("Starting Telegram updates listener...")
    from app.telegram_bot import start_telegram_listener
    start_telegram_listener()
    
    yield
    # Shutdown actions
    logger.info("Shutting down AutoHeal...")

app = FastAPI(title="AutoHeal Autonomous SRE", version="2.0.0", lifespan=lifespan)

# Register modular API routers
app.include_router(incidents.router)
app.include_router(upgrades.router)
app.include_router(settings.router)
app.include_router(usage.router)

# Mount frontend assets if compiled dist exists
if os.path.exists(FRONTEND_DIST):
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

@app.get("/api/dashboard")
def get_dashboard_data(db: Session = Depends(get_db)):
    """Unified dashboard state aggregation endpoint."""
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING", "BLOCKED"]
    
    active_count = db.query(Incident).filter(Incident.status.in_(active_statuses)).count()
    resolved_count = db.query(Incident).filter(Incident.status == "RESOLVED").count()
    targets_count = db.query(Target).count()
    
    now = datetime.utcnow()
    ignored_count = db.query(Target).filter(
        Target.ignored_until.is_not(None),
        Target.ignored_until > now
    ).count()
    
    active_incidents = db.query(Incident).filter(
        Incident.status.in_(active_statuses)
    ).order_by(Incident.created_at.desc()).all()
    
    ignored_targets = db.query(Target).filter(
        Target.ignored_until.is_not(None),
        Target.ignored_until > now
    ).all()
    
    history_incidents = db.query(Incident).filter(
        Incident.status.notin_(active_statuses)
    ).order_by(Incident.created_at.desc()).limit(100).all()
    
    def serialize_incidents(list_inc):
        return [{
            "id": inc.id,
            "target_id": inc.target_id,
            "status": inc.status,
            "category": inc.category or "unknown",
            "error_logs": inc.error_logs,
            "root_cause": inc.root_cause,
            "proposed_fix": inc.proposed_fix,
            "execution_log": inc.execution_log,
            "completed_at": inc.completed_at.isoformat() if inc.completed_at else None,
            "created_at": inc.created_at.isoformat() if inc.created_at else None
        } for inc in list_inc]
        
    def serialize_targets(list_targ):
        return [{
            "id": t.id,
            "type": t.type,
            "ignored_until": t.ignored_until.isoformat() if t.ignored_until else None
        } for t in list_targ]
        
    is_active, reason = check_maintenance_status(db)

    return {
        "active_count": active_count,
        "resolved_count": resolved_count,
        "targets_count": targets_count,
        "ignored_count": ignored_count,
        "active_incidents": serialize_incidents(active_incidents),
        "ignored_targets": serialize_targets(ignored_targets),
        "history_incidents": serialize_incidents(history_incidents),
        "maintenance_active": is_active,
        "maintenance_reason": reason,
        "autopilot": get_setting("autopilot") == "true",
        "silent_mode": get_setting("silent_mode") == "true"
    }

@app.get("/", response_class=HTMLResponse)
def get_root_ui(request: Request, db: Session = Depends(get_db)):
    """Serve React frontend if built, or fallback to legacy Jinja2."""
    index_file = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)

    # Fallback to legacy Jinja2 template
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING", "BLOCKED"]
    active_count = db.query(Incident).filter(Incident.status.in_(active_statuses)).count()
    resolved_count = db.query(Incident).filter(Incident.status == "RESOLVED").count()
    targets_count = db.query(Target).count()
    
    now = datetime.utcnow()
    ignored_count = db.query(Target).filter(
        Target.ignored_until.is_not(None),
        Target.ignored_until > now
    ).count()

    active_incidents = db.query(Incident).filter(
        Incident.status.in_(active_statuses)
    ).order_by(Incident.created_at.desc()).all()

    ignored_targets = db.query(Target).filter(
        Target.ignored_until.is_not(None),
        Target.ignored_until > now
    ).all()

    history_incidents = db.query(Incident).filter(
        Incident.status.notin_(active_statuses)
    ).order_by(Incident.created_at.desc()).limit(100).all()

    is_active, reason = check_maintenance_status(db)

    return templates.TemplateResponse(request, "index.html", {
        "active_count": active_count,
        "resolved_count": resolved_count,
        "targets_count": targets_count,
        "ignored_count": ignored_count,
        "active_incidents": active_incidents,
        "ignored_targets": ignored_targets,
        "history_incidents": history_incidents,
        "token": WEBHOOK_TOKEN,
        "maintenance_mode": get_setting("maintenance_mode", "false"),
        "maintenance_active": is_active,
        "maintenance_reason": reason
    })

# Catch-all route for SPA client-side routing
@app.get("/{full_path:path}")
async def catch_all_spa(full_path: str):
    if full_path.startswith("api") or full_path.startswith("messages") or full_path.startswith("sse"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    index_file = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    raise HTTPException(status_code=404, detail="Page not found")

# ----------------------------------------------------
# MCP SERVER INTEGRATION
# ----------------------------------------------------

@mcp_server.list_tools()
async def list_tools() -> List[Tool]:
    return [
        Tool(
            name="search_incidents",
            description="Perform semantic search on past resolved Docker incidents to find resolutions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query (e.g. permission error, network timeout)"},
                    "limit": {"type": "integer", "description": "Max number of incidents to return.", "default": 5}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_incident_history",
            description="Get chronological history of incidents for a target container.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target_id": {"type": "string", "description": "Name of the target Docker container."},
                    "limit": {"type": "integer", "description": "Max history size.", "default": 10}
                },
                "required": ["target_id"]
            }
        ),
        Tool(
            name="trigger_remediation",
            description="Approve and trigger automated SRE remediation command for a PENDING_USER incident.",
            inputSchema={
                "type": "object",
                "properties": {
                    "incident_id": {"type": "string", "description": "UUID of the active incident."}
                },
                "required": ["incident_id"]
            }
        )
    ]

@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict) -> List[TextContent]:
    db = SessionLocal()
    try:
        if name == "search_incidents":
            query = arguments["query"]
            limit = arguments.get("limit", 5)
            from app.qdrant_mem import qdrant_mem
            matches = qdrant_mem.semantic_search(query, limit=limit)
            if not matches:
                return [TextContent(type="text", text="No similar incidents found in memory.")]
            
            results = []
            for hit in matches:
                inc = db.query(Incident).filter(Incident.id == hit.id).first()
                if inc:
                    results.append(
                        f"Incident ID: {inc.id}\nTarget: {inc.target_id}\nCategory: {inc.category or 'unknown'}\n"
                        f"Score: {hit.score:.4f}\nRoot Cause: {inc.root_cause}\nFix: {inc.proposed_fix}\n"
                        f"----------------------------------------"
                    )
            return [TextContent(type="text", text="\n\n".join(results) if results else "No matching incidents in database.")]
            
        elif name == "get_incident_history":
            target_id = arguments["target_id"]
            limit = arguments.get("limit", 10)
            rows = db.query(Incident).filter(Incident.target_id == target_id).order_by(Incident.created_at.desc()).limit(limit).all()
            if not rows:
                return [TextContent(type="text", text=f"No incident history found for container '{target_id}'")]
            
            history = []
            for r in rows:
                history.append(f"[{r.created_at}] Status: {r.status} | Category: {r.category or 'unknown'}\nCause: {r.root_cause}\nFix: {r.proposed_fix}")
            return [TextContent(type="text", text="\n\n".join(history))]
            
        elif name == "trigger_remediation":
            incident_id = arguments["incident_id"]
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if not incident:
                return [TextContent(type="text", text="Error: Incident not found.")]
            if incident.status in ["FIXING", "RESOLVED"]:
                return [TextContent(type="text", text=f"Incident already processed in state {incident.status}")]
            
            incident.status = "FIXING"
            db.commit()
            
            from app.remediator import run_remediation
            threading.Thread(target=run_remediation, args=(incident_id,), daemon=True).start()
            return [TextContent(type="text", text=f"Remediation spawned for incident {incident_id} on target {incident.target_id}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error executing tool: {e}")]
    finally:
        db.close()

# Mount SSE endpoints
@app.get("/sse")
async def sse_endpoint(request: Request):
    logger.info("New MCP client SSE connection requested.")
    async with sse_transport.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        await mcp_server.run(read_stream, write_stream, mcp_server.create_initialization_options())

app.mount("/messages", sse_transport.handle_post_message)
