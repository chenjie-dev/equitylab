from datetime import datetime, timezone

from fastapi import APIRouter

from app.models import HealthBody
from app.rag import qdrant_store

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthBody)
def health() -> HealthBody:
    return HealthBody(ts=datetime.now(timezone.utc).isoformat())


@router.get("/ready")
def ready() -> dict:
    """就绪探测：附带 Qdrant 状态，不因向量库短暂不可用而 5xx（MVP）。"""
    q = qdrant_store.probe_qdrant()
    return {"status": "UP", "service": "research", "qdrant": q}
