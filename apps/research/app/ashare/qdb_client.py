"""A 股读路径适配：协议走 equitylab_qdb；行映射留在本模块。"""

from __future__ import annotations

from typing import Any

from equitylab_qdb import Client

_client = Client(timeout=5.0)


def qdb_symbol(code: str) -> str:
    digits = "".join(ch for ch in code if ch.isdigit())
    code6 = digits[-6:].zfill(6) if digits else ""
    exchange = "SSE" if code6.startswith(("5", "6", "9")) else "SZSE"
    return f"{exchange}:{code6}"


def klines(symbol: str, period: str) -> list[dict[str, Any]]:
    return _client.klines(symbol, period)


def snapshots_all() -> dict[str, Any]:
    body = _client.snapshots_body()
    if body.get("error"):
        return body
    return {
        "data": [_quote_row(item) for item in body.get("data") or []],
        "source": "qdb",
        "scale": body.get("scale", 10000),
    }


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
    body = _client.snapshots_body(symbols)
    if body.get("error"):
        return {"data": [], "source": "qdb", "error": "qdb_unavailable"}
    rows = [_quote_row(item) for item in body.get("data") or []]
    return {"data": rows, "source": "qdb", "scale": body.get("scale", 10000)}
