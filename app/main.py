import os
import logging
import threading
from typing import List
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Query, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import init_db, get_db, Target, Incident, SessionLocal
from app.watcher import start_watcher_thread
from app.scheduler import start_scheduler
from app.remediator import run_remediation

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
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN")
if not WEBHOOK_TOKEN:
    raise ValueError("WEBHOOK_TOKEN environment variable must be set!")
PORT = int(os.getenv("PORT", "9013"))
HOST = os.getenv("HOST", "0.0.0.0")

# Setup templates
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

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
    
    logger.info("Starting configuration file watcher...")
    from app.fswatcher import start_fswatcher_thread
    start_fswatcher_thread()
    
    logger.info("Starting Telegram updates listener...")
    from app.telegram_bot import start_telegram_listener
    start_telegram_listener()
    
    yield
    # Shutdown actions (if any)
    logger.info("Shutting down AutoHeal...")

app = FastAPI(title="AutoHeal Autonomous SRE", lifespan=lifespan)

class WebhookPayload(BaseModel):
    action: str  # fix, defer, ignore

@app.get("/", response_class=HTMLResponse)
def get_dashboard(request: Request, db: Session = Depends(get_db)):
    # 1. Fetch counts
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING"]
    active_count = db.query(Incident).filter(Incident.status.in_(active_statuses)).count()
    resolved_count = db.query(Incident).filter(Incident.status == "RESOLVED").count()
    targets_count = db.query(Target).count()
    
    now = datetime.utcnow()
    ignored_count = db.query(Target).filter(
        Target.ignored_until.is_not(None),
        Target.ignored_until > now
    ).count()

    # 2. Fetch records
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

    return templates.TemplateResponse(request, "index.html", {
        "active_count": active_count,
        "resolved_count": resolved_count,
        "targets_count": targets_count,
        "ignored_count": ignored_count,
        "active_incidents": active_incidents,
        "ignored_targets": ignored_targets,
        "history_incidents": history_incidents,
        "token": WEBHOOK_TOKEN
    })

@app.post("/api/webhooks/{incident_id}")
async def handle_webhook(
    incident_id: str,
    payload: WebhookPayload,
    background_tasks: BackgroundTasks,
    token: str = Query(...),
    db: Session = Depends(get_db)
):
    # 1. Authenticate secret token
    if token != WEBHOOK_TOKEN:
        logger.warning(f"Unauthorized webhook trigger attempt. Token: {token}")
        raise HTTPException(status_code=401, detail="Invalid auth token")

    # 2. Query incident
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    # 3. Idempotency Check
    action = payload.action.lower()
    if incident.status in ["FIXING", "RESOLVED", "DEFERRED", "IGNORED"]:
        logger.info(f"Incident {incident_id} already in status {incident.status}. Webhook ignored (duplicate hit).")
        return {"status": "ok", "detail": f"Already processed in state {incident.status}"}

    # 4. Handle actions
    now = datetime.utcnow()
    if action == "defer":
        logger.info(f"Deferring incident {incident_id} by 24 hours.")
        incident.deferred_until = now + timedelta(hours=24)
        incident.status = "DEFERRED"
        db.commit()
        return {"status": "ok", "detail": "Incident deferred for 24h"}

    elif action == "ignore":
        logger.info(f"Ignoring target '{incident.target_id}' permanently.")
        target = db.query(Target).filter(Target.id == incident.target_id).first()
        if target:
            target.ignored_until = datetime(9999, 12, 31, 23, 59, 59)
        incident.status = "IGNORED"
        db.commit()
        return {"status": "ok", "detail": f"Target {incident.target_id} permanently ignored"}

    elif action == "fix":
        logger.info(f"Approved fix for incident {incident_id}. Spawning remediation worker...")
        incident.status = "FIXING"
        db.commit()
        # Spawn remediation async worker task in the background
        background_tasks.add_task(run_remediation, incident_id)
        return {"status": "ok", "detail": "Remediation triggered"}

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")

@app.post("/api/targets/{target_id}/unignore")
def unignore_target(target_id: str, db: Session = Depends(get_db)):
    target = db.query(Target).filter(Target.id == target_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    
    target.ignored_until = None
    db.commit()
    logger.info(f"Manually unignored target '{target_id}' via API.")
    return {"status": "ok", "detail": "Target unignored"}

@app.get("/api/incidents/active")
def get_active_incidents(db: Session = Depends(get_db)):
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING"]
    incidents = db.query(Incident).filter(Incident.status.in_(active_statuses)).all()
    return incidents

@app.get("/api/incidents/history")
def get_history_incidents(db: Session = Depends(get_db)):
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING"]
    incidents = db.query(Incident).filter(Incident.status.notin_(active_statuses)).all()
    return incidents

@app.get("/api/incidents/search")
def search_incidents(q: str = Query(...), db: Session = Depends(get_db)):
    from app.qdrant_mem import qdrant_mem
    # Perform semantic query in Qdrant
    matches = qdrant_mem.semantic_search(q, limit=10)
    if not matches:
        return []
    
    # Retrieve incident details from SQL using matched IDs
    incident_ids = [match.id for match in matches]
    incidents = db.query(Incident).filter(Incident.id.in_(incident_ids)).all()
    
    # Sort incidents in order of their Qdrant match score
    id_to_score = {match.id: match.score for match in matches}
    sorted_incidents = sorted(incidents, key=lambda x: id_to_score.get(x.id, 0), reverse=True)
    
    # Return formatted results with similarity scores
    results = []
    for inc in sorted_incidents:
        results.append({
            "id": inc.id,
            "target_id": inc.target_id,
            "status": inc.status,
            "category": inc.category or "unknown",
            "root_cause": inc.root_cause,
            "proposed_fix": inc.proposed_fix,
            "completed_at": inc.completed_at.isoformat() if inc.completed_at else None,
            "score": id_to_score.get(inc.id, 0)
        })
    return results

@app.get("/api/dashboard")
def get_dashboard_data(db: Session = Depends(get_db)):
    active_statuses = ["DETECTED", "INVESTIGATING", "PENDING_USER", "FIXING"]
    
    # Counts
    active_count = db.query(Incident).filter(Incident.status.in_(active_statuses)).count()
    resolved_count = db.query(Incident).filter(Incident.status == "RESOLVED").count()
    targets_count = db.query(Target).count()
    
    now = datetime.utcnow()
    ignored_count = db.query(Target).filter(
        Target.ignored_until.is_not(None),
        Target.ignored_until > now
    ).count()
    
    # Lists
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
    
    # Serialize helper
    def serialize_incidents(list_inc):
        return [{
            "id": inc.id,
            "target_id": inc.target_id,
            "status": inc.status,
            "category": inc.category or "unknown",
            "root_cause": inc.root_cause,
            "proposed_fix": inc.proposed_fix,
            "execution_log": inc.execution_log,
            "completed_at": inc.completed_at.isoformat() if inc.completed_at else None,
            "created_at": inc.created_at.isoformat()
        } for inc in list_inc]
        
    def serialize_targets(list_targ):
        return [{
            "id": t.id,
            "type": t.type,
            "ignored_until": t.ignored_until.isoformat() if t.ignored_until else None
        } for t in list_targ]
        
    return {
        "active_count": active_count,
        "resolved_count": resolved_count,
        "targets_count": targets_count,
        "ignored_count": ignored_count,
        "active_incidents": serialize_incidents(active_incidents),
        "ignored_targets": serialize_targets(ignored_targets),
        "history_incidents": serialize_incidents(history_incidents)
    }

class SettingsUpdate(BaseModel):
    silent_mode: bool | None = None
    autopilot: bool | None = None

@app.get("/api/settings")
def get_system_settings():
    from app.database import get_setting
    return {
        "silent_mode": get_setting("silent_mode") == "true",
        "autopilot": get_setting("autopilot") == "true"
    }

@app.post("/api/settings")
def update_system_settings(settings: SettingsUpdate):
    from app.database import set_setting
    if settings.silent_mode is not None:
        set_setting("silent_mode", "true" if settings.silent_mode else "false")
    if settings.autopilot is not None:
        set_setting("autopilot", "true" if settings.autopilot else "false")
    return {"status": "success"}

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
            # Perform search in Qdrant
            from app.qdrant_mem import qdrant_mem
            matches = qdrant_mem.semantic_search(query, limit=limit)
            if not matches:
                return [TextContent(type="text", text="No similar incidents found in memory.")]
            
            # Map matches to SQL
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
            
            # Trigger remediation async
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
