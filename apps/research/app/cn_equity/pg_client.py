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


def _day_s(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value)[:10]


def capital_flow_daily(
    code: str,
    *,
    exchange: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """个股日度资金流（新→旧）。"""
    inner = resolve_inner_code(code, exchange=exchange)
    if inner is None:
        return []
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit), 500))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT trading_day, main_net, super_large_net, large_net, medium_net, small_net
            FROM market.capital_flow_daily
            WHERE inner_code=%s
            ORDER BY trading_day DESC
            LIMIT %s
            """,
            (inner, lim),
        )
        return [
            {
                "trading_day": _day_s(r[0]),
                "main_net": _f(r[1]),
                "super_large_net": _f(r[2]),
                "large_net": _f(r[3]),
                "medium_net": _f(r[4]),
                "small_net": _f(r[5]),
            }
            for r in cur.fetchall()
        ]


def finance_core(
    code: str,
    *,
    exchange: str | None = None,
    report_limit: int = 4,
    indicators: list[str] | None = None,
) -> list[dict[str, Any]]:
    """核心财务长表；默认最近若干报告期的常用指标。"""
    inner = resolve_inner_code(code, exchange=exchange)
    if inner is None:
        return []
    conn = _connect()
    if conn is None:
        return []
    want = indicators or [
        "basic_eps",
        "net_profit_attr_sh",
        "total_rev",
        "roe_wtd",
        "gross_margin",
        "net_margin",
        "asset_liab_ratio",
    ]
    rl = max(1, min(int(report_limit), 40))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT report_date FROM market.finance_core
            WHERE inner_code=%s
            ORDER BY report_date DESC
            LIMIT %s
            """,
            (inner, rl),
        )
        days = [r[0] for r in cur.fetchall()]
        if not days:
            return []
        cur.execute(
            """
            SELECT report_date, indicator_code, indicator_name, value, unit
            FROM market.finance_core
            WHERE inner_code=%s AND report_date = ANY(%s)
              AND indicator_code = ANY(%s)
            ORDER BY report_date DESC, indicator_code
            """,
            (inner, days, want),
        )
        return [
            {
                "report_date": _day_s(r[0]),
                "indicator_code": r[1],
                "indicator_name": r[2] or "",
                "value": _f(r[3]),
                "unit": r[4] or "",
            }
            for r in cur.fetchall()
        ]


def share_capital_latest(
    code: str, *, exchange: str | None = None
) -> dict[str, Any] | None:
    inner = resolve_inner_code(code, exchange=exchange)
    if inner is None:
        return None
    conn = _connect()
    if conn is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT change_date, total_shares, float_shares, float_shares_a, change_reason
            FROM market.share_capital
            WHERE inner_code=%s
            ORDER BY change_date DESC
            LIMIT 1
            """,
            (inner,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "change_date": _day_s(row[0]),
        "total_shares": _f(row[1]),
        "float_shares": _f(row[2]),
        "float_shares_a": _f(row[3]),
        "change_reason": row[4] or "",
    }


def security_industries(
    code: str, *, exchange: str | None = None
) -> list[dict[str, Any]]:
    inner = resolve_inner_code(code, exchange=exchange)
    if inner is None:
        return []
    conn = _connect()
    if conn is None:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT si.industry_code, sw.name, sw.level, si.effective_from
            FROM market.security_industry si
            JOIN market.industry_sw sw ON sw.industry_code = si.industry_code
            WHERE si.inner_code=%s AND si.effective_to IS NULL
            ORDER BY sw.level
            """,
            (inner,),
        )
        return [
            {
                "industry_code": r[0],
                "name": r[1] or "",
                "level": int(r[2]),
                "effective_from": _day_s(r[3]),
            }
            for r in cur.fetchall()
        ]


def lifting(
    code: str,
    *,
    exchange: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    inner = resolve_inner_code(code, exchange=exchange)
    if inner is None:
        return []
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit), 200))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT lift_date, shares, ratio, holder_type, remark
            FROM market.lifting
            WHERE inner_code=%s
            ORDER BY lift_date DESC
            LIMIT %s
            """,
            (inner, lim),
        )
        return [
            {
                "lift_date": _day_s(r[0]),
                "shares": _f(r[1]),
                "ratio": _f(r[2]),
                "holder_type": r[3] or "",
                "remark": r[4] or "",
            }
            for r in cur.fetchall()
        ]


def list_plates(
    *,
    vendor: str = "east",
    q: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    v = (vendor or "east").strip().lower()
    if v not in ("ths", "east"):
        return []
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit), 2000))
    qq = (q or "").strip()
    with conn.cursor() as cur:
        if qq:
            cur.execute(
                """
                SELECT vendor, plate_code, name, plate_kind
                FROM market.plate
                WHERE vendor=%s AND (plate_code ILIKE %s OR name ILIKE %s)
                ORDER BY updated_at DESC NULLS LAST, plate_code
                LIMIT %s
                """,
                (v, f"%{qq}%", f"%{qq}%", lim),
            )
        else:
            cur.execute(
                """
                SELECT vendor, plate_code, name, plate_kind
                FROM market.plate
                WHERE vendor=%s
                ORDER BY updated_at DESC NULLS LAST, plate_code
                LIMIT %s
                """,
                (v, lim),
            )
        return [
            {
                "vendor": r[0],
                "plate_code": r[1],
                "name": r[2] or "",
                "plate_kind": r[3] or "",
            }
            for r in cur.fetchall()
        ]


def plate_members(
    vendor: str,
    plate_code: str,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    v = (vendor or "").strip().lower()
    pcode = (plate_code or "").strip()
    if v not in ("ths", "east") or not pcode:
        return []
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit), 2000))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.exchange_code, s.secu_code, s.name
            FROM market.plate_member pm
            JOIN market.security s ON s.inner_code = pm.inner_code
            WHERE pm.vendor=%s AND pm.plate_code=%s AND pm.effective_to IS NULL
            ORDER BY s.secu_code
            LIMIT %s
            """,
            (v, pcode, lim),
        )
        out = []
        for ex, code, name in cur.fetchall():
            ui = _EX_UI.get(str(ex), "SZ")
            out.append(
                {
                    "stock_code": str(code),
                    "short_name": str(name or ""),
                    "exchange": ui,
                    "symbol": f"{code}.{ui}",
                    "qdb_exchange": str(ex),
                }
            )
        return out


def capital_flow_plate_daily(
    *,
    vendor: str = "east",
    trading_day: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """板块资金流快照；缺省取最新交易日。"""
    v = (vendor or "east").strip().lower()
    if v not in ("ths", "east"):
        return []
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit), 500))
    with conn.cursor() as cur:
        day = trading_day
        if not day:
            cur.execute(
                """
                SELECT MAX(trading_day) FROM market.capital_flow_plate_daily
                WHERE vendor=%s
                """,
                (v,),
            )
            row = cur.fetchone()
            if not row or not row[0]:
                return []
            day = row[0]
        cur.execute(
            """
            SELECT c.trading_day, c.plate_code, p.name, c.main_net,
                   c.super_large_net, c.large_net, c.medium_net, c.small_net
            FROM market.capital_flow_plate_daily c
            LEFT JOIN market.plate p
              ON p.vendor=c.vendor AND p.plate_code=c.plate_code
            WHERE c.vendor=%s AND c.trading_day=%s
            ORDER BY c.main_net DESC NULLS LAST
            LIMIT %s
            """,
            (v, day, lim),
        )
        return [
            {
                "trading_day": _day_s(r[0]),
                "plate_code": r[1],
                "name": r[2] or "",
                "main_net": _f(r[3]),
                "super_large_net": _f(r[4]),
                "large_net": _f(r[5]),
                "medium_net": _f(r[6]),
                "small_net": _f(r[7]),
            }
            for r in cur.fetchall()
        ]


def margin_balance_recent(*, limit: int = 30) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit), 500))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT trading_day, market_scope, financing_balance,
                   securities_balance, margin_balance
            FROM market.margin_balance
            ORDER BY trading_day DESC
            LIMIT %s
            """,
            (lim,),
        )
        return [
            {
                "trading_day": _day_s(r[0]),
                "market_scope": r[1],
                "financing_balance": _f(r[2]),
                "securities_balance": _f(r[3]),
                "margin_balance": _f(r[4]),
            }
            for r in cur.fetchall()
        ]


def north_flow_recent(*, limit: int = 30) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit), 500))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT trading_day, net_flow, buy_amount, sell_amount, sh_net, sz_net
            FROM market.north_flow_daily
            ORDER BY trading_day DESC
            LIMIT %s
            """,
            (lim,),
        )
        return [
            {
                "trading_day": _day_s(r[0]),
                "net_flow": _f(r[1]),
                "buy_amount": _f(r[2]),
                "sell_amount": _f(r[3]),
                "sh_net": _f(r[4]),
                "sz_net": _f(r[5]),
            }
            for r in cur.fetchall()
        ]


def hot_rank_daily(
    *,
    vendor: str | None = None,
    rank_type: str | None = None,
    trading_day: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit), 200))
    with conn.cursor() as cur:
        day = trading_day
        if not day:
            cur.execute("SELECT MAX(trading_day) FROM market.hot_rank_daily")
            row = cur.fetchone()
            if not row or not row[0]:
                return []
            day = row[0]
        clauses = ["trading_day=%s"]
        args: list[Any] = [day]
        if vendor:
            clauses.append("vendor=%s")
            args.append(vendor.strip().lower())
        if rank_type:
            clauses.append("rank_type=%s")
            args.append(rank_type.strip())
        args.append(lim)
        cur.execute(
            f"""
            SELECT h.trading_day, h.vendor, h.rank_type, h.rank_no,
                   s.secu_code, s.name, h.plate_vendor, h.plate_code, h.name, h.score
            FROM market.hot_rank_daily h
            LEFT JOIN market.security s ON s.inner_code = h.inner_code
            WHERE {' AND '.join(clauses)}
            ORDER BY h.rank_no
            LIMIT %s
            """,
            tuple(args),
        )
        return [
            {
                "trading_day": _day_s(r[0]),
                "vendor": r[1],
                "rank_type": r[2],
                "rank_no": int(r[3]),
                "stock_code": r[4] or "",
                "stock_name": r[5] or "",
                "plate_vendor": r[6] or "",
                "plate_code": r[7] or "",
                "name": r[8] or "",
                "score": _f(r[9]),
            }
            for r in cur.fetchall()
        ]


def lhb_list_daily(
    trading_day: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit), 500))
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT l.trading_day, s.exchange_code, s.secu_code, s.name,
                   l.list_reason, l.close, l.change_pct, l.amount, l.net_buy, l.id
            FROM market.lhb_list l
            JOIN market.security s ON s.inner_code = l.inner_code
            WHERE l.trading_day=%s
            ORDER BY l.net_buy DESC NULLS LAST
            LIMIT %s
            """,
            (trading_day[:10], lim),
        )
        out = []
        for r in cur.fetchall():
            ui = _EX_UI.get(str(r[1]), "SZ")
            out.append(
                {
                    "trading_day": _day_s(r[0]),
                    "stock_code": str(r[2]),
                    "short_name": str(r[3] or ""),
                    "exchange": ui,
                    "list_reason": r[4] or "",
                    "close": _f(r[5]),
                    "change_pct": _f(r[6]),
                    "amount": _f(r[7]),
                    "net_buy": _f(r[8]),
                    "id": int(r[9]),
                }
            )
        return out
