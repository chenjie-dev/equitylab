"""从 Postgres `market` schema 读已闭合历史棒。

DATABASE_URL 未配置或查询失败时返回空，由调用方回落 qdb。
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger("equitylab.research.cn_equity.pg")

_lock = threading.Lock()
_conn = None  # type: ignore[var-annotated]
SH = ZoneInfo("Asia/Shanghai")

# k_type → (store, period)
_PERIOD_MAP = {
    "1d": ("daily", None),
    "5m": ("minute", "5m"),
    "15m": ("minute", "15m"),
    "60m": ("minute", "60m"),
    "1h": ("minute", "60m"),
    "1m": ("minute", "1m"),
    # 周/月：读日线后由 service 折叠
    "1w": ("daily", None),
    "1M": ("daily", None),
    # 30m：读 15m 后折叠
    "30m": ("minute", "15m"),
}


def enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL", "").strip())


def _connect():
    global _conn
    if not enabled():
        return None
    with _lock:
        if _conn is not None:
            try:
                _conn.cursor().execute("SELECT 1")
                return _conn
            except Exception:
                try:
                    _conn.close()
                except Exception:
                    pass
                _conn = None
        try:
            import psycopg2

            _conn = psycopg2.connect(os.environ["DATABASE_URL"])
            _conn.autocommit = True
            return _conn
        except Exception as exc:
            logger.warning("pg connect failed: %s", exc)
            return None


def _f(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _exchange_for(code: str) -> str:
    from app.cn_equity.qdb_client import cn_equity_exchange

    return cn_equity_exchange(code)


def resolve_inner_code(code: str) -> int | None:
    code6 = "".join(ch for ch in str(code) if ch.isdigit())[-6:].zfill(6)
    ex = _exchange_for(code6)
    conn = _connect()
    if conn is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT inner_code FROM market.security
            WHERE exchange_code=%s AND secu_code=%s
            """,
            (ex, code6),
        )
        row = cur.fetchone()
    return int(row[0]) if row else None


def bars(
    code: str,
    k_type: str,
    *,
    limit: int = 300,
) -> list[dict[str, Any]]:
    """返回与 qdb 蜡烛同形的 history 行；无数据则 []。"""
    mapping = _PERIOD_MAP.get(k_type)
    if not mapping:
        return []
    store, period = mapping
    fold = {"30m": 2, "1w": 7, "1M": 31}.get(k_type, 1)
    want = max(1, int(limit) if limit > 0 else 300)
    raw_limit = min(5000, want * fold + fold)

    inner = resolve_inner_code(code)
    if inner is None:
        return []
    conn = _connect()
    if conn is None:
        return []

    candles: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        if store == "daily":
            cur.execute(
                """
                SELECT trading_day, open, high, low, close, volume
                FROM market.bar_daily
                WHERE inner_code=%s
                ORDER BY trading_day DESC
                LIMIT %s
                """,
                (inner, raw_limit),
            )
            rows = list(reversed(cur.fetchall()))
            for trading_day, o, h, l, c, vol in rows:
                day: date = trading_day
                # 日 K：上海日 00:00 的 epoch ms（与旧 _parse_ts_ms UTC 日切不同；
                # 统一用上海午夜，便于与盘中 session 对齐）
                ts_ms = int(
                    datetime(day.year, day.month, day.day, tzinfo=SH).timestamp() * 1000
                )
                candles.append(
                    {
                        "time": ts_ms,
                        "open": _f(o),
                        "high": _f(h),
                        "low": _f(l),
                        "close": _f(c),
                        "volume": _f(vol),
                        "trade_date": day.isoformat(),
                        "bar_kind": "history",
                    }
                )
        else:
            cur.execute(
                """
                SELECT bar_time, trading_day, open, high, low, close, volume
                FROM market.bar_minute
                WHERE inner_code=%s AND period=%s
                ORDER BY bar_time DESC
                LIMIT %s
                """,
                (inner, period, raw_limit),
            )
            rows = list(reversed(cur.fetchall()))
            for bar_time, trading_day, o, h, l, c, vol in rows:
                bt: datetime = bar_time
                if bt.tzinfo is None:
                    bt = bt.replace(tzinfo=timezone.utc)
                local = bt.astimezone(SH)
                day_s = (
                    trading_day.isoformat()
                    if isinstance(trading_day, date)
                    else local.strftime("%Y-%m-%d")
                )
                candles.append(
                    {
                        "time": int(bt.timestamp() * 1000),
                        "open": _f(o),
                        "high": _f(h),
                        "low": _f(l),
                        "close": _f(c),
                        "volume": _f(vol),
                        "trade_date": day_s,
                        "bar_kind": "history",
                    }
                )
    return candles


def adjust_factors(code: str) -> list[dict[str, Any]]:
    """复权因子列表（升序）；读路径按需变换，库内不存复权价。"""
    inner = resolve_inner_code(code)
    if inner is None:
        return []
    conn = _connect()
    if conn is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ex_date, forward_factor, backward_factor
            FROM market.adjust_factor
            WHERE inner_code=%s
            ORDER BY ex_date
            """,
            (inner,),
        )
        return [
            {
                "ex_date": r[0].isoformat(),
                "forward_factor": _f(r[1]),
                "backward_factor": _f(r[2]),
            }
            for r in cur.fetchall()
        ]
