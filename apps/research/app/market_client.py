"""行情 K 线消费者：A 股走 market 冷库（经 cn-equity pg），其它走 market-data。"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

from app.observability import trace_headers

DEFAULT_MARKET_DATA_URL = "http://127.0.0.1:3002"
TIMEOUT_S = 15.0

_CN_SUFFIX = re.compile(r"^(?P<code>\d{6})\.(?P<ex>SH|SZ|BJ)$", re.I)
_CN_PREFIX = re.compile(r"^(?P<ex>SSE|SZSE|BSE):(?P<code>\d{6})$", re.I)


def market_data_base() -> str:
    return os.getenv("MARKET_DATA_URL", DEFAULT_MARKET_DATA_URL).rstrip("/")


def parse_cn_equity_universe(symbol: str) -> tuple[str, str] | None:
    """识别 A 股宇宙 → (exchange_ui SH|SZ|BJ, code6)；非 A 股返回 None。"""
    raw = (symbol or "").strip().upper()
    if not raw:
        return None
    m = _CN_SUFFIX.match(raw)
    if m:
        return m.group("ex").upper(), m.group("code")
    m = _CN_PREFIX.match(raw)
    if m:
        ex = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}[m.group("ex").upper()]
        return ex, m.group("code")
    if re.fullmatch(r"\d{6}", raw):
        ex = "SH" if raw.startswith(("5", "6", "9")) else "SZ"
        if raw.startswith(("4", "8")) or raw.startswith("92"):
            ex = "BJ"
        return ex, raw
    return None


def _bars_from_market_pg(
    code: str, *, exchange: str, count: int
) -> tuple[list[dict[str, Any]], str]:
    from app.cn_equity import pg_client

    ex_qdb = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(exchange.upper(), "SSE")
    rows = pg_client.bars(code, "1d", limit=count, exchange=ex_qdb)
    # dual_ma 需要 close + datetime/date
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "datetime": r.get("trade_date") or "",
                "date": r.get("trade_date") or "",
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("close"),
                "volume": r.get("volume"),
            }
        )
    return out, "postgres:market.bar_daily"


async def fetch_bars(
    symbol: str,
    *,
    period: str = "1d",
    count: int = 120,
    adjust: str = "none",
) -> list[dict[str, Any]]:
    """A 股日线优先 market；否则 GET market-data /bars/{symbol}。"""
    cn = parse_cn_equity_universe(symbol)
    if cn and period in ("1d", "d", "day", "1D"):
        ex, code = cn
        bars, _src = _bars_from_market_pg(code, exchange=ex, count=count)
        if bars:
            fetch_bars.last_source = _src  # type: ignore[attr-defined]
            return bars
        # 冷库空则回落 market-data（可能仍无）
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
    fetch_bars.last_source = f"{market_data_base()}/bars/{symbol}"  # type: ignore[attr-defined]
    return data


def last_bars_source() -> str:
    return str(getattr(fetch_bars, "last_source", "") or "")
