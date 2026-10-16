"""从 market-data 拉取 K 线（研究层只做消费者，不缓存行情）。"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.observability import trace_headers

DEFAULT_MARKET_DATA_URL = "http://127.0.0.1:3002"
TIMEOUT_S = 15.0


def market_data_base() -> str:
    return os.getenv("MARKET_DATA_URL", DEFAULT_MARKET_DATA_URL).rstrip("/")


async def fetch_bars(
    symbol: str,
    *,
    period: str = "1d",
    count: int = 120,
    adjust: str = "none",
) -> list[dict[str, Any]]:
    """GET /bars/{symbol}；失败抛 httpx.HTTPError。透传 X-Trace-Id。"""
    url = f"{market_data_base()}/bars/{symbol}"
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        res = await client.get(
            url,
            params={"period": period, "count": count, "adjust": adjust},
            headers=trace_headers(),
        )
        res.raise_for_status()
        data = res.json()
    if not isinstance(data, list):
        raise ValueError("bars response is not a list")
    return data
