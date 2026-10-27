"""中国 A 股公开行情 API —— 只读；`/cn-equity` 为规范前缀。"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.cn_equity.service import service

logger = logging.getLogger("equitylab.research.cn_equity")

# 无前缀的端点集，由 /cn-equity 挂载
endpoints = APIRouter()


class Catalog(BaseModel):
    id: str = "cn-equity"
    name: str = "China A-share equity (cn-equity)"
    auth: str = "none"
    note: str = (
        "只读。历史优先 Postgres market.*；盘中/订阅读 qdb。"
        "采集在 collector；data_source 可含 sina，非业务资源名。"
    )
    endpoints: list[str] = Field(
        default_factory=lambda: [
            "GET /cn-equity/codes?q=&limit=&category=stock|index|etf|convertible",
            "GET /cn-equity/quotes?codes=000001,SSE:000001&category=",
            "GET /cn-equity/index-strip",
            "GET /cn-equity/klines/{code}?k_type=1d&view=merged&exchange=&category=",
            "GET /cn-equity/five/{code}",
            "GET /cn-equity/intraday/{code}",
        ]
    )


@endpoints.get("/")
async def catalog() -> Catalog:
    return Catalog()


@endpoints.get("/codes")
async def codes(
    q: Annotated[str | None, Query(description="代码或名称关键词")] = None,
    limit: Annotated[int, Query(ge=1, le=12000)] = 10000,
    category: Annotated[
        str,
        Query(description="stock|index|etf|convertible；非 stock 读 market.security"),
    ] = "stock",
) -> dict:
    try:
        return await asyncio.to_thread(service.list_codes, q, limit, category)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("cn-equity codes failed")
        raise HTTPException(status_code=502, detail=f"cn-equity codes: {e}") from e


@endpoints.get("/quotes")
async def quotes(
    codes: Annotated[
        str,
        Query(description="逗号分隔：000001 或 SSE:000001 / 000001.SH，最多 80"),
    ],
    category: Annotated[
        str | None,
        Query(description="可选；index/etf 等缺 qdb 时回落 bar_daily"),
    ] = None,
) -> dict:
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    try:
        return await asyncio.to_thread(
            service.quotes, code_list, category=category
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("cn-equity quotes failed")
        raise HTTPException(status_code=502, detail=f"cn-equity quotes: {e}") from e


@endpoints.get("/index-strip")
async def index_strip() -> dict:
    """顶栏主流指数报价（同花顺/东财常见六指数）。"""
    try:
        return await asyncio.to_thread(service.index_strip)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("cn-equity index-strip failed")
        raise HTTPException(
            status_code=502, detail=f"cn-equity index-strip: {e}"
        ) from e


@endpoints.get("/klines/{code}")
async def klines(
    code: str,
    k_type: Annotated[str, Query()] = "1d",
    start_date: Annotated[str | None, Query()] = None,
    end_date: Annotated[str | None, Query()] = None,
    adjust_type: Annotated[int, Query(ge=0, le=2)] = 1,
    limit: Annotated[int, Query(ge=1, le=2000)] = 300,
    view: Annotated[
        str,
        Query(
            description="history=已完成 | realtime=盘中未完成 | merged=合成图"
        ),
    ] = "merged",
    exchange: Annotated[
        str | None,
        Query(description="SSE/SZSE/BSE 或 SH/SZ/BJ；指数勿省略"),
    ] = None,
    category: Annotated[
        str | None,
        Query(description="stock|index|etf|convertible"),
    ] = None,
) -> dict:
    try:
        return await asyncio.to_thread(
            service.klines,
            code,
            k_type,
            start_date,
            end_date,
            adjust_type,
            limit,
            view,
            exchange,
            category,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("cn-equity klines failed code=%s", code)
        raise HTTPException(status_code=502, detail=f"cn-equity klines: {e}") from e


@endpoints.get("/five/{code}")
async def five(
    code: str,
    exchange: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
) -> dict:
    try:
        return await asyncio.to_thread(
            service.five, code, exchange=exchange, category=category
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("cn-equity five failed code=%s", code)
        raise HTTPException(status_code=502, detail=f"cn-equity five: {e}") from e


@endpoints.get("/intraday/{code}")
async def intraday(
    code: str,
    exchange: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
) -> dict:
    try:
        return await asyncio.to_thread(
            service.intraday, code, exchange=exchange, category=category
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("cn-equity intraday failed code=%s", code)
        raise HTTPException(status_code=502, detail=f"cn-equity intraday: {e}") from e


router = APIRouter(prefix="/cn-equity", tags=["cn-equity"])
router.include_router(endpoints)
