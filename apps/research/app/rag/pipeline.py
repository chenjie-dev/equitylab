"""RAG 流水线骨架（对齐 langchain-rag + 立项 chunk 参数）。

流水线：Load → Split(800/150) → Embed → Qdrant → Retrieve → (Rerank) → Prompt
MVP：无真实 Embedding 时回落演示切片；有 Qdrant 时尝试元数据检索集合健康度。
"""

from __future__ import annotations

from typing import Any

# 立项约定；与 RecursiveCharacterTextSplitter 默认用法一致
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
COLLECTION_NAME = "equitylab_reports"


def split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """简易字符切分（后续可替换为 langchain_text_splitters.RecursiveCharacterTextSplitter）。"""
    if chunk_size <= 0:
        return [text]
    step = max(chunk_size - overlap, 1)
    chunks: list[str] = []
    i = 0
    while i < len(text):
        chunks.append(text[i : i + chunk_size])
        i += step
    return chunks or [text]


def demo_hits(query: str, top_k: int) -> list[dict[str, Any]]:
    """诚实 stub：演示召回，禁止当作生产检索结果。"""
    return [
        {
            "doc_id": "demo-report-1",
            "title": "演示研报：示例标的投资要点",
            "score": 0.72,
            "snippet": f"与「{query}」相关的演示切片（chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}）。",
            "source": "DEMO",
        }
    ][:top_k]


def build_search_response(
    query: str,
    top_k: int,
    *,
    qdrant_status: str,
    mode: str,
) -> dict[str, Any]:
    return {
        "query": query,
        "mode": mode,
        "chunk": {"size": CHUNK_SIZE, "overlap": CHUNK_OVERLAP},
        "collection": COLLECTION_NAME,
        "qdrant": qdrant_status,
        "hits": demo_hits(query, top_k),
        "note": "Embedding + hybrid/RRF 未启用；当前为 deterministic demo hits",
    }
