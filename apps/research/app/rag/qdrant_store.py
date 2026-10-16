"""Qdrant 客户端封装（qdrant-clients-sdk 约定）。

集合不存在或服务不可达时降级，不阻断研究层启动。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .pipeline import COLLECTION_NAME

logger = logging.getLogger("equitylab.research.qdrant")


def get_qdrant_url() -> str:
    return os.getenv("QDRANT_URL", "http://127.0.0.1:6333")


def probe_qdrant() -> dict[str, Any]:
    """探测 Qdrant 可达性与目标集合是否存在。"""
    url = get_qdrant_url()
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=url, prefer_grpc=False, timeout=3.0)
        collections = client.get_collections().collections
        names = {c.name for c in collections}
        return {
            "ok": True,
            "url": url,
            "collection_exists": COLLECTION_NAME in names,
            "collections": sorted(names),
        }
    except Exception as exc:  # noqa: BLE001 — 探测失败必须降级
        logger.warning("qdrant probe failed: %s", exc)
        return {"ok": False, "url": url, "error": str(exc)}


def ensure_collection(vector_size: int = 1536) -> dict[str, Any]:
    """确保研报集合存在（cosine）；幂等。默认维度对齐 text-embedding-3-large 截断前常用 1536。"""
    url = get_qdrant_url()
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http import models as rest

        client = QdrantClient(url=url, prefer_grpc=False, timeout=5.0)
        names = {c.name for c in client.get_collections().collections}
        if COLLECTION_NAME not in names:
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=rest.VectorParams(size=vector_size, distance=rest.Distance.COSINE),
            )
            return {"created": True, "collection": COLLECTION_NAME, "vector_size": vector_size}
        return {"created": False, "collection": COLLECTION_NAME, "vector_size": vector_size}
    except Exception as exc:  # noqa: BLE001
        return {"created": False, "error": str(exc), "url": url}
