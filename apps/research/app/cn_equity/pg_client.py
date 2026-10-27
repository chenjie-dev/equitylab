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


_EX_UI = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}
_UI_EX = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE", "SSE": "SSE", "SZSE": "SZSE", "BSE": "BSE"}


def _exchange_for(code: str) -> str:
    from app.cn_equity.qdb_client import cn_equity_exchange

    return cn_equity_exchange(code)


def index_exchange_for(code: str) -> str:
    """指数号段：000/880→SSE，399/395→SZSE（勿用个股前缀）。"""
    c = "".join(ch for ch in str(code) if ch.isdigit())[-6:].zfill(6)
    if c.startswith(("399", "395", "980")):
        return "SZSE"
    if c.startswith(("4", "8")) or c.startswith("92"):
        return "BSE"
    if c.startswith(("000", "880", "999")):
        return "SSE"
    return _exchange_for(c)


def normalize_exchange(raw: str | None, *, code: str = "", category: str | None = None) -> str:
    """UI/qdb 交易所 → SSE/SZSE/BSE。"""
    if raw:
        key = str(raw).strip().upper()
        if key in _UI_EX:
            return _UI_EX[key]
    if (category or "").lower() == "index":
        return index_exchange_for(code)
    return _exchange_for(code)


def resolve_inner_code(
    code: str,
    *,
    exchange: str | None = None,
    category: str | None = None,
) -> int | None:
    code6 = "".join(ch for ch in str(code) if ch.isdigit())[-6:].zfill(6)
    ex = normalize_exchange(exchange, code=code6, category=category)
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
        if row:
            return int(row[0])
        # 指数/ETF 偶发挂错所：再按 category 规则试一次
        if category and category != "stock":
            alt = index_exchange_for(code6) if category == "index" else _exchange_for(code6)
            if alt != ex:
                cur.execute(
                    """
                    SELECT inner_code FROM market.security
                    WHERE exchange_code=%s AND secu_code=%s
                    """,
                    (alt, code6),
                )
                row = cur.fetchone()
                if row:
                    return int(row[0])
    return None


def list_securities(
    category: str,
    *,
    q: str | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """按 secu_category 列目录（index / etf / convertible）。"""
    cat = (category or "").strip().lower()
    if cat not in ("index", "etf", "convertible"):
        return []
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit or 5000), 12000))
    # 指数：主流代码优先，避免 LIMIT 被北交所冷门号段占满
    order_sql = "ORDER BY exchange_code, secu_code"
    if cat == "index":
        order_sql = """
            ORDER BY CASE secu_code
              WHEN '000001' THEN 0 WHEN '399001' THEN 1 WHEN '399006' THEN 2
              WHEN '000300' THEN 3 WHEN '000016' THEN 4 WHEN '000852' THEN 5
              WHEN '000905' THEN 6 WHEN '399005' THEN 7 ELSE 100 END,
              exchange_code, secu_code
        """
    elif cat == "etf":
        order_sql = """
            ORDER BY CASE secu_code
              WHEN '510300' THEN 0 WHEN '159915' THEN 1 WHEN '512880' THEN 2
              WHEN '159919' THEN 3 ELSE 100 END,
              exchange_code, secu_code
        """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT exchange_code, secu_code, name, secu_category
            FROM market.security
            WHERE secu_category = %s
            {order_sql}
            LIMIT %s
            """,
            (cat, lim),
        )
        rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    qq = (q or "").strip().upper()
    for ex, code, name, secu_cat in rows:
        code_s = str(code)
        name_s = str(name or "")
        ex_s = str(ex)
        # 指数：丢掉误挂交易所的影子行（如 SZSE:000001=平安银行被标成 index）
        if cat == "index":
            if code_s.startswith(("399", "395", "980")) and ex_s != "SZSE":
                continue
            if code_s.startswith(("000", "880", "999")) and ex_s != "SSE":
                continue
        ui = _EX_UI.get(ex_s, "SZ")
        if qq and qq not in code_s and qq not in name_s.upper() and qq not in f"{code_s}.{ui}":
            continue
        out.append(
            {
                "stock_code": code_s,
                "short_name": name_s,
                "exchange": ui,
                "symbol": f"{code_s}.{ui}",
                "category": secu_cat,
                "qdb_exchange": ex_s,
            }
        )
    return out


def last_daily_quotes(
    pairs: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """(exchange SSE/SZSE/BSE, code6) → 最近一根日线合成报价。"""
    if not pairs:
        return []
    conn = _connect()
    if conn is None:
        return []
    out: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        for ex, code in pairs:
            code6 = "".join(ch for ch in str(code) if ch.isdigit())[-6:].zfill(6)
            ex_n = normalize_exchange(ex, code=code6)
            cur.execute(
                """
                SELECT s.name, s.secu_category, b.trading_day, b.open, b.high, b.low,
                       b.close, b.prev_close, b.volume, b.amount
                FROM market.security s
                JOIN market.bar_daily b ON b.inner_code = s.inner_code
                WHERE s.exchange_code=%s AND s.secu_code=%s
                ORDER BY b.trading_day DESC
                LIMIT 1
                """,
                (ex_n, code6),
            )
            row = cur.fetchone()
            if not row:
                continue
            name, cat, day, o, h, l, c, prev, vol, amt = row
            close = _f(c)
            pre = _f(prev)
            if pre is None or pre == 0:
                # 再取前一日收盘
                cur.execute(
                    """
                    SELECT close FROM market.bar_daily
                    WHERE inner_code = (
                      SELECT inner_code FROM market.security
                      WHERE exchange_code=%s AND secu_code=%s
                    ) AND trading_day < %s
                    ORDER BY trading_day DESC LIMIT 1
                    """,
                    (ex_n, code6, day),
                )
                prev_row = cur.fetchone()
                pre = _f(prev_row[0]) if prev_row else None
            change = None
            change_pct = None
            if close is not None and pre is not None and pre != 0:
                change = round(close - pre, 4)
                change_pct = round((close - pre) / pre * 100, 2)
            ui = _EX_UI.get(ex_n, "SZ")
            out.append(
                {
                    "stock_code": code6,
                    "short_name": str(name or ""),
                    "exchange": ui,
                    "symbol": f"{code6}.{ui}",
                    "category": str(cat or ""),
                    "price": close,
                    "open": _f(o),
                    "high": _f(h),
                    "low": _f(l),
                    "pre_close": pre,
                    "change": change,
                    "change_pct": change_pct,
                    "volume": _f(vol),
                    "amount": _f(amt),
                    "trade_date": day.isoformat() if hasattr(day, "isoformat") else str(day),
                    "source": "postgres:bar_daily",
                }
            )
    return out


def bars(
    code: str,
    k_type: str,
    *,
    limit: int = 300,
    exchange: str | None = None,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """返回与 qdb 蜡烛同形的 history 行；无数据则 []。"""
    mapping = _PERIOD_MAP.get(k_type)
    if not mapping:
        return []
    store, period = mapping
    fold = {"30m": 2, "1w": 7, "1M": 31}.get(k_type, 1)
    want = max(1, int(limit) if limit > 0 else 300)
    raw_limit = min(5000, want * fold + fold)

    inner = resolve_inner_code(code, exchange=exchange, category=category)
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
