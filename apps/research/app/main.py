"""EquityLab 研究计算层（Python / FastAPI）。

按 FastAPI 最佳实践拆分 router；RAG 对齐立项 chunk 与 Qdrant 探测。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routers import backtests, factors, health, rag

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("equitylab.research")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("research starting; QDRANT_URL=%s", os.getenv("QDRANT_URL", ""))
    yield
    logger.info("research shutdown")


def create_app() -> FastAPI:
    application = FastAPI(
        title="EquityLab Research",
        version="0.2.0",
        description="量化研究层：RAG / 因子 / 回测。",
        lifespan=lifespan,
    )
    application.include_router(health.router)
    application.include_router(rag.router)
    application.include_router(factors.router)
    application.include_router(backtests.router)
    return application


app = create_app()
