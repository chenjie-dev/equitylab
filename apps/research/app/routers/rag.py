from typing import Any

from fastapi import APIRouter

from app.models import RagSearchRequest
from app.rag import qdrant_store
from app.rag.pipeline import build_search_response

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/search")
def rag_search(body: RagSearchRequest) -> dict[str, Any]:
    """检索私有研报切片。"""
    probe = qdrant_store.probe_qdrant()
    mode = "qdrant-aware-stub" if probe.get("ok") else "offline-stub"
    status = "up" if probe.get("ok") else f"down:{probe.get('error', 'unknown')}"
    return build_search_response(
        body.query,
        body.top_k,
        qdrant_status=status,
        mode=mode,
    )


@router.post("/collections/ensure")
def ensure_collection() -> dict[str, Any]:
    """幂等创建研报向量集合（无写入向量；供运维/初始化）。"""
    return qdrant_store.ensure_collection()
