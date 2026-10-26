"""中国 A 股读路径适配：协议走 equitylab_qdb；行映射留在本模块。"""

from __future__ import annotations

from typing import Any

from equitylab_qdb import Client

# snapshots 宜短超时；klines 在写压高时可能 >5s，单独加长
_client = Client(timeout=5.0)
_klines_client = Client(timeout=20.0)


def cn_equity_exchange(code: str) -> str:
    """6 位 A 股码 → qdb 交易所标签（与 collector 一致）。

    北交所：4/8 开头或 92xxxx；须先于「9→SSE」，避免 920088 误标沪市。
    """
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    code6 = digits[-6:].zfill(6) if digits else ""
    if code6.startswith(("4", "8")) or code6.startswith("92"):
        return "BSE"
    if code6.startswith(("5", "6", "9")):
        return "SSE"
    return "SZSE"


def qdb_symbol(code: str) -> str:
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    code6 = digits[-6:].zfill(6) if digits else ""
    return f"{cn_equity_exchange(code6)}:{code6}"


def klines(
    symbol: str,
    period: str,
    *,
    limit: int | None = None,
    end_time_ms: int | None = None,
) -> list[dict[str, Any]]:
    """窗口读；对齐 qdb `GET /v1/klines` 的 `limit` / `endTime`（手册上限 5000）。"""
    return _klines_client.klines(symbol, period, limit=limit, end_time_ms=end_time_ms)


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
    # snapshots 偶发带 bid_px1/ask_px1（scale）或 bid/ask（浮点）
    bid = item.get("bid")
    ask = item.get("ask")
    if bid is None and item.get("bid_px1") is not None:
        from equitylab_qdb import unscale

        bid = unscale(item["bid_px1"])
    if ask is None and item.get("ask_px1") is not None:
        from equitylab_qdb import unscale

        ask = unscale(item["ask_px1"])
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
        "bid": bid,
        "ask": ask,
        "symbol": item.get("symbol"),
        "seq": item.get("seq"),
        "exchange": item.get("exchange"),
    }


def depth_doc(code: str) -> dict[str, Any] | None:
    """读 collector 写入的 `cn-equity:depth:{EX}:{code}` 五档 docs。"""
    symbol = qdb_symbol(code)
    body = _client.get_doc(f"cn-equity:depth:{symbol}")
    if not body:
        return None
    # GET /v1/docs 可能直接返回 value，或包一层 {key,value}
    if isinstance(body, dict) and "bids" in body:
        return body
    if isinstance(body, dict) and isinstance(body.get("value"), dict):
        return body["value"]
    return None


def codes_catalog() -> dict[str, Any] | None:
    """读 collector 写入的全市场代码表 `cn-equity:codes`。"""
    body = _client.get_doc("cn-equity:codes")
    if not body:
        return None
    if isinstance(body, dict) and isinstance(body.get("codes"), list):
        return body
    if isinstance(body, dict) and isinstance(body.get("value"), dict):
        value = body["value"]
        if isinstance(value.get("codes"), list):
            return value
    return None


def snapshots(codes: list[str]) -> dict[str, Any]:
    symbols = [qdb_symbol(c) for c in codes if c]
    if not symbols:
        return {"data": [], "source": "qdb"}
    body = _client.snapshots_body(symbols)
    if body.get("error"):
        return {"data": [], "source": "qdb", "error": "qdb_unavailable"}
    rows = [_quote_row(item) for item in body.get("data") or []]
    return {"data": rows, "source": "qdb", "scale": body.get("scale", 10000)}
