import uuid
import logging
import requests
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import SessionLocal, AIUsageLog

logger = logging.getLogger("AIUsage")

# Pricing table per 1M tokens ($ USD)
MODEL_RATES = {
    "qwen3.5-flash-02-23": {"input": 0.10, "output": 0.20},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-3.5-flash-medium": {"input": 0.15, "output": 0.60},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "default": {"input": 0.10, "output": 0.25}
}

def estimate_tokens_from_text(text: str) -> int:
    """Rough estimation of tokens (4 chars ~ 1 token)."""
    if not text:
        return 0
    return max(1, len(text) // 4)

def calculate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = MODEL_RATES.get(model_id, MODEL_RATES["default"])
    input_cost = (prompt_tokens / 1_000_000.0) * rates["input"]
    output_cost = (completion_tokens / 1_000_000.0) * rates["output"]
    return round(input_cost + output_cost, 6)

def record_ai_usage(
    incident_id: str | None,
    executor: str,
    model_id: str,
    prompt_text: str = "",
    completion_text: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_sec: float = 0.0,
    status: str = "SUCCESS"
) -> AIUsageLog | None:
    """Record an AI invocation with token counts and cost estimation."""
    if prompt_tokens == 0 and prompt_text:
        prompt_tokens = estimate_tokens_from_text(prompt_text)
    if completion_tokens == 0 and completion_text:
        completion_tokens = estimate_tokens_from_text(completion_text)
        
    total_tokens = prompt_tokens + completion_tokens
    cost = calculate_cost(model_id, prompt_tokens, completion_tokens)
    
    db: Session = SessionLocal()
    try:
        log_entry = AIUsageLog(
            id=str(uuid.uuid4()),
            incident_id=incident_id,
            executor=executor,
            model_id=model_id,
            prompt_tokens=str(prompt_tokens),
            completion_tokens=str(completion_tokens),
            total_tokens=str(total_tokens),
            cost_usd=f"{cost:.6f}",
            duration_sec=f"{duration_sec:.2f}",
            status=status,
            created_at=datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry
    except Exception as e:
        logger.error(f"Failed to record AI usage log: {e}")
        db.rollback()
        return None
    finally:
        db.close()

def get_ai_usage_summary() -> dict:
    """Aggregate total spend, token count, and model breakdown."""
    db: Session = SessionLocal()
    try:
        logs = db.query(AIUsageLog).order_by(AIUsageLog.created_at.desc()).all()
        total_calls = len(logs)
        total_tokens = 0
        total_cost = 0.0
        model_counts = {}
        executor_counts = {}
        
        for entry in logs:
            try:
                tokens = int(entry.total_tokens or 0)
                cost = float(entry.cost_usd or 0.0)
            except ValueError:
                tokens = 0
                cost = 0.0
                
            total_tokens += tokens
            total_cost += cost
            
            m = entry.model_id or "unknown"
            model_counts[m] = model_counts.get(m, 0) + 1
            
            ex = entry.executor or "unknown"
            executor_counts[ex] = executor_counts.get(ex, 0) + 1

        # Check if LiteLLM server has additional spend info
        litellm_status = "unreachable"
        try:
            res = requests.get("http://localhost:8448/health", timeout=1)
            if res.status_code == 200:
                litellm_status = "healthy"
        except Exception:
            pass

        return {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "model_counts": model_counts,
            "executor_counts": executor_counts,
            "litellm_status": litellm_status,
            "recent_logs": [{
                "id": l.id,
                "incident_id": l.incident_id,
                "executor": l.executor,
                "model_id": l.model_id,
                "prompt_tokens": l.prompt_tokens,
                "completion_tokens": l.completion_tokens,
                "total_tokens": l.total_tokens,
                "cost_usd": l.cost_usd,
                "duration_sec": l.duration_sec,
                "status": l.status,
                "created_at": l.created_at.isoformat() if l.created_at else None
            } for l in logs[:50]]
        }
    except Exception as e:
        logger.error(f"Error fetching AI usage summary: {e}")
        return {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "model_counts": {},
            "executor_counts": {},
            "litellm_status": "error",
            "recent_logs": []
        }
    finally:
        db.close()
