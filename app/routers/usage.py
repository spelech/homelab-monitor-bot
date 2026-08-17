import logging
from fastapi import APIRouter
from app.ai_usage import get_ai_usage_summary

logger = logging.getLogger("UsageRouter")

router = APIRouter(prefix="/api/usage", tags=["usage"])

@router.get("/summary")
def get_usage_summary():
    """Retrieve AI token usage, costs, and model metrics."""
    return get_ai_usage_summary()
