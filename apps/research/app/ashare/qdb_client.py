"""只读客户端：实时行情从本机 qdb 拉，不回源公开接口。"""

from __future__ import annotations

import os
from typing import Any

import requests

QDB_URL = os.environ.get("QDB_URL", "http://127.0.0.1:9090").rstrip("/")


def qdb_symbol(code: str) -> str:
    digits = "".join(ch for ch in code if ch.isdigit())
    code6 = digits[-6:].zfill(6) if digits else ""
    exchange = "SSE" if code6.startswith(("5", "6", "9")) else "SZSE"
    return f"{exchange}:{code6}"


def klines(symbol: str, period: str) -> list[dict[str, Any]]:
    try:
        r = requests.get(
            f"{QDB_URL}/v1/klines",
            params={"symbol": symbol, "period": period},
            timeout=5,
        )
        if r.status_code == 404:
            return []
        r.raise_for_status()
        body = r.json()
    except Exception:
        return []
    return list(body.get("data") or [])


def snapshots_all() -> dict[str, Any]:
    try:
        r = requests.get(f"{QDB_URL}/v1/snapshots", timeout=2.5)
        r.raise_for_status()
        body = r.json()
    except Exception:
        return {"data": [], "source": "qdb", "error": "qdb_unavailable"}
    return {"data": [_quote_row(item) for item in body.get("data") or []], "source": "qdb"}


def _quote_row(item: dict[str, Any]) -> dict[str, Any]:
    price = item.get("price")
    pre = item.get("pre_close")
    change = None
    change_pct = None
    if price is not None and pre not in (None, 0):
        change = round(float(price) - float(pre), 4)
        change_pct = round(change / float(pre) * 100, 2)
    return {
        "stock_code": str(item.get("code") or ""),
        "short_name": item.get("name") or "",
        "price": price,
        "open": item.get("open"),
        "high": item.get("high"),
        "low": item.get("low"),
        "pre_close": pre,
        "change": change,
        "change_pct": change_pct,
        "volume": item.get("volume"),
        "amount": item.get("amount"),
        "symbol": item.get("symbol"),
        "seq": item.get("seq"),
        "exchange": item.get("exchange"),
    }


def snapshots(codes: list[str]) -> dict[str, Any]:
    symbols = [qdb_symbol(c) for c in codes if c]
    if not symbols:
        return {"data": [], "source": "qdb"}
    try:
        r = requests.get(
            f"{QDB_URL}/v1/snapshots",
            params={"symbols": ",".join(symbols)},
            timeout=2.5,
        )
        r.raise_for_status()
        body = r.json()
    except Exception:
        return {"data": [], "source": "qdb", "error": "qdb_unavailable"}
    rows = [_quote_row(item) for item in body.get("data") or []]
    return {"data": rows, "source": "qdb", "scale": body.get("scale", 10000)}
