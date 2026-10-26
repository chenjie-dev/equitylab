"""EquityLab 研究计算层（Python / FastAPI）。

按 FastAPI 最佳实践拆分 router；RAG 对齐立项 chunk 与 Qdrant 探测。
统一 X-Trace-Id + JSON 日志。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.observability import TraceMiddleware, setup_logging
from app.routers import backtests, cn_equity, factors, health, rag

setup_logging()
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
        description="量化研究层：RAG / 因子 / 回测 / 中国 A 股行情(cn-equity)。",
        lifespan=lifespan,
    )
    application.add_middleware(TraceMiddleware)
    application.include_router(health.router)
    application.include_router(rag.router)
    application.include_router(factors.router)
    application.include_router(backtests.router)
    application.include_router(cn_equity.router)
    # Prometheus：用 FastAPI 路由模板（{code}），避免真实 code 高基数
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            excluded_handlers=["/metrics"],
        ).instrument(application).expose(
            application, endpoint="/metrics", include_in_schema=False
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("prometheus instrumentator unavailable: %s", exc)
    return application


app = create_app()
