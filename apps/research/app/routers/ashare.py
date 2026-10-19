"""A 股公开行情 API（adata）——只读。"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.ashare.service import service

logger = logging.getLogger("equitylab.research.ashare")

router = APIRouter(prefix="/ashare", tags=["ashare"])


class Catalog(BaseModel):
    id: str = "adata-ashare"
    name: str = "A-share public quotes (adata)"
    auth: str = "none"
    upstream: str = "https://github.com/1nchaos/adata"
    note: str = "只读 qdb。公开源采集在 collector 服务，不在读路径回源。"
    endpoints: list[str] = Field(
        default_factory=lambda: [
            "GET /ashare/codes?q=&limit=",
            "GET /ashare/quotes?codes=000001,600519",
            "GET /ashare/klines/{code}?k_type=1d&view=merged&limit=",
            "GET /ashare/five/{code}",
            "GET /ashare/intraday/{code}",
        ]
    )


@router.get("/")
async def catalog() -> Catalog:
    return Catalog()


@router.get("/codes")
async def codes(
    q: Annotated[str | None, Query(description="代码或名称关键词")] = None,
    limit: Annotated[int, Query(ge=1, le=8000)] = 5000,
) -> dict:
    try:
        return await asyncio.to_thread(service.list_codes, q, limit)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("ashare codes failed")
        raise HTTPException(status_code=502, detail=f"adata codes: {e}") from e


@router.get("/quotes")
async def quotes(
    codes: Annotated[
        str,
        Query(description="逗号分隔 6 位代码，最多 80 个"),
    ],
) -> dict:
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    try:
        return await asyncio.to_thread(service.quotes, code_list)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("ashare quotes failed")
        raise HTTPException(status_code=502, detail=f"adata quotes: {e}") from e


@router.get("/klines/{code}")
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
            description="history=已完成(WSD) | realtime=盘中未完成(WSQ/WSI) | merged=合成图"
        ),
    ] = "merged",
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
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("ashare klines failed code=%s", code)
        raise HTTPException(status_code=502, detail=f"adata klines: {e}") from e


@router.get("/five/{code}")
async def five(code: str) -> dict:
    try:
        return await asyncio.to_thread(service.five, code)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("ashare five failed code=%s", code)
        raise HTTPException(status_code=502, detail=f"adata five: {e}") from e


@router.get("/intraday/{code}")
async def intraday(code: str) -> dict:
    try:
        return await asyncio.to_thread(service.intraday, code)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("ashare intraday failed code=%s", code)
        raise HTTPException(status_code=502, detail=f"adata intraday: {e}") from e
