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
            "GET /cn-equity/fundamentals/{code}",
            "GET /cn-equity/plates?vendor=east|ths",
            "GET /cn-equity/plates/{vendor}/{plate_code}/members",
            "GET /cn-equity/plate-flow?vendor=east",
            "GET /cn-equity/sentiment/summary",
            "GET /cn-equity/lhb?date=YYYY-MM-DD",
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


@endpoints.get("/fundamentals/{code}")
async def fundamentals(
    code: str,
    exchange: Annotated[str | None, Query()] = None,
    flow_limit: Annotated[int, Query(ge=1, le=120)] = 20,
    finance_reports: Annotated[int, Query(ge=1, le=20)] = 4,
) -> dict:
    """个股冷域：资金流 / 财务 / 股本 / 申万 / 解禁（只读 market）。"""
    try:
        return await asyncio.to_thread(
            service.fundamentals,
            code,
            exchange=exchange,
            flow_limit=flow_limit,
            finance_reports=finance_reports,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("cn-equity fundamentals failed code=%s", code)
        raise HTTPException(
            status_code=502, detail=f"cn-equity fundamentals: {e}"
        ) from e


@endpoints.get("/plates")
async def plates(
    vendor: Annotated[str, Query(description="ths|east")] = "east",
    q: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> dict:
    try:
        return await asyncio.to_thread(
            service.plates, vendor=vendor, q=q, limit=limit
        )
    except Exception as e:
        logger.exception("cn-equity plates failed")
        raise HTTPException(status_code=502, detail=f"cn-equity plates: {e}") from e


@endpoints.get("/plates/{vendor}/{plate_code}/members")
async def plate_members(
    vendor: str,
    plate_code: str,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> dict:
    try:
        return await asyncio.to_thread(
            service.plate_members, vendor, plate_code, limit=limit
        )
    except Exception as e:
        logger.exception("cn-equity plate members failed")
        raise HTTPException(
            status_code=502, detail=f"cn-equity plate members: {e}"
        ) from e


@endpoints.get("/plate-flow")
async def plate_flow(
    vendor: Annotated[str, Query()] = "east",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    try:
        return await asyncio.to_thread(
            service.plate_flow, vendor=vendor, limit=limit
        )
    except Exception as e:
        logger.exception("cn-equity plate-flow failed")
        raise HTTPException(
            status_code=502, detail=f"cn-equity plate-flow: {e}"
        ) from e


@endpoints.get("/sentiment/summary")
async def sentiment_summary() -> dict:
    try:
        return await asyncio.to_thread(service.sentiment_summary)
    except Exception as e:
        logger.exception("cn-equity sentiment failed")
        raise HTTPException(
            status_code=502, detail=f"cn-equity sentiment: {e}"
        ) from e


@endpoints.get("/lhb")
async def lhb(
    date: Annotated[str, Query(description="YYYY-MM-DD 上榜日")],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    try:
        return await asyncio.to_thread(service.lhb, date, limit=limit)
    except Exception as e:
        logger.exception("cn-equity lhb failed")
        raise HTTPException(status_code=502, detail=f"cn-equity lhb: {e}") from e


router = APIRouter(prefix="/cn-equity", tags=["cn-equity"])
router.include_router(endpoints)
