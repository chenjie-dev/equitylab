"""新浪公开 K 线拉取（仅授权采集族使用；读路径禁止）。"""

from __future__ import annotations

from typing import Any

import requests

from equitylab_market.symbols import cn_equity_exchange, code6

_UA = {
    "User-Agent": "equitylab-market",
    "Referer": "https://finance.sina.com.cn",
}
_KLINE_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)


def sina_symbol(code: str) -> str:
    c = code6(code) or "000000"
    prefix = {"SSE": "sh", "SZSE": "sz", "BSE": "bj"}[cn_equity_exchange(c)]
    return prefix + c


def klines(code: str, *, scale_min: int, limit: int, timeout: float = 25.0) -> list[dict[str, Any]]:
    """拉取新浪 K 线；scale_min=240 为日线，5 为 5 分钟等。"""
    r = requests.get(
        _KLINE_URL,
        params={
            "symbol": sina_symbol(code),
            "scale": scale_min,
            "ma": "no",
            "datalen": limit,
        },
        headers=_UA,
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return []
    return [
        {
            "day": str(item.get("day") or ""),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "close": item.get("close"),
            "volume": item.get("volume") or 0,
        }
        for item in data
        if item.get("day")
    ]


def daily_klines(code: str, limit: int = 200, *, timeout: float = 25.0) -> list[dict[str, Any]]:
    return klines(code, scale_min=240, limit=limit, timeout=timeout)
