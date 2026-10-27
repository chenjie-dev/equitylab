"""Postgres `market` schema 冷库写与覆盖查询（equitylab_market.pg）。

边界（docs/market/2026-10-26-行情模块边界.md）：
- 只写冷数据；盘中热路径仍走 qdb，勿在此写未闭合棒。
- `source_code` 为 data_source（sina / adata / eastmoney / ths 等），不是产品 API 名。
- DATABASE_URL 未配置或库不可达时 no-op。

表结构：
- 基线：docs/market/2026-10-26-market-postgres-schema.md（bar_daily / adjust_factor / …）
- adata 完整冷域：docs/market/2026-10-27-market-schema-adata完整域.md
  （plate / index_member / capital_flow_* / finance_core / 舆情等；列注释见
  infra/postgres/migrations/20261027_market_schema_adata.sql）

本模块当前实现以日线覆盖与 sina 写入为主；完整域写入按该文档 P0–P3 分阶段扩展。
"""

from __future__ import annotations

import os
import threading
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

_lock = threading.Lock()
_conn = None  # type: ignore[var-annotated]
_inner_cache: dict[tuple[str, str], int] = {}
_warned = False

SH = ZoneInfo("Asia/Shanghai")


def enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL", "").strip())


def _connect():
    global _conn, _warned
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
            if not _warned:
                print(f"equitylab_market.pg: DATABASE_URL connect failed: {exc}", flush=True)
                _warned = True
            return None


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _bigint(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def ensure_security(
    exchange_code: str,
    secu_code: str,
    *,
    name: str = "",
    secu_category: str = "stock",
) -> int | None:
    """确保 security 行存在，返回 inner_code。"""
    key = (exchange_code, secu_code)
    if key in _inner_cache:
        return _inner_cache[key]
    conn = _connect()
    if conn is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.security (exchange_code, secu_code, name, secu_category)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (exchange_code, secu_code) DO UPDATE
              SET name = CASE
                    WHEN EXCLUDED.name <> '' THEN EXCLUDED.name
                    ELSE market.security.name
                  END,
                  updated_at = NOW()
            RETURNING inner_code
            """,
            (exchange_code, secu_code, name or "", secu_category),
        )
        row = cur.fetchone()
    if not row:
        return None
    inner = int(row[0])
    _inner_cache[key] = inner
    return inner


def upsert_bar_daily(
    exchange_code: str,
    secu_code: str,
    trading_day: date | str,
    bar: dict[str, Any],
    *,
    source_code: str = "sina",
    name: str = "",
) -> bool:
    """写入 / 覆盖一根日线（交易所原始价）。"""
    inner = ensure_security(exchange_code, secu_code, name=name)
    if inner is None:
        return False
    day = trading_day if isinstance(trading_day, date) else date.fromisoformat(str(trading_day)[:10])
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.bar_daily (
                inner_code, trading_day, prev_close, open, high, low, close,
                volume, amount, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (inner_code, trading_day) DO UPDATE SET
                prev_close = EXCLUDED.prev_close,
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                amount = EXCLUDED.amount,
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (
                inner,
                day,
                _dec(bar.get("prev_close") or bar.get("pre_close")),
                _dec(bar.get("open")),
                _dec(bar.get("high")),
                _dec(bar.get("low")),
                _dec(bar.get("close")),
                _bigint(bar.get("volume")),
                _dec(bar.get("amount")),
                source_code,
            ),
        )
    return True


def upsert_bar_minute(
    exchange_code: str,
    secu_code: str,
    period: str,
    bar_time: datetime,
    trading_day: date | str,
    bar: dict[str, Any],
    *,
    source_code: str = "sina",
    name: str = "",
) -> bool:
    """写入 / 覆盖一根分钟线；bar_time 须为 aware UTC 或带时区。"""
    if period not in ("1m", "5m", "15m", "60m"):
        return False
    inner = ensure_security(exchange_code, secu_code, name=name)
    if inner is None:
        return False
    day = trading_day if isinstance(trading_day, date) else date.fromisoformat(str(trading_day)[:10])
    if bar_time.tzinfo is None:
        bar_time = bar_time.replace(tzinfo=timezone.utc)
    else:
        bar_time = bar_time.astimezone(timezone.utc)
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.bar_minute (
                inner_code, period, bar_time, trading_day,
                open, high, low, close, volume, amount, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (inner_code, period, bar_time) DO UPDATE SET
                trading_day = EXCLUDED.trading_day,
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                amount = EXCLUDED.amount,
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (
                inner,
                period,
                bar_time,
                day,
                _dec(bar.get("open")),
                _dec(bar.get("high")),
                _dec(bar.get("low")),
                _dec(bar.get("close")),
                _bigint(bar.get("volume")),
                _dec(bar.get("amount")),
                source_code,
            ),
        )
    return True


def upsert_adjust_factor(
    exchange_code: str,
    secu_code: str,
    ex_date: date | str,
    *,
    forward_factor: Any = 1,
    backward_factor: Any = 1,
    source_code: str = "sina",
) -> bool:
    inner = ensure_security(exchange_code, secu_code)
    if inner is None:
        return False
    day = ex_date if isinstance(ex_date, date) else date.fromisoformat(str(ex_date)[:10])
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.adjust_factor (
                inner_code, ex_date, forward_factor, backward_factor, source_code
            ) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (inner_code, ex_date) DO UPDATE SET
                forward_factor = EXCLUDED.forward_factor,
                backward_factor = EXCLUDED.backward_factor,
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (inner, day, _dec(forward_factor) or Decimal(1), _dec(backward_factor) or Decimal(1), source_code),
        )
    return True


def upsert_calendar_day(
    exchange_code: str,
    calendar_date: date | str,
    *,
    is_trading_day: bool,
    prev_trading_day: date | str | None = None,
    next_trading_day: date | str | None = None,
) -> bool:
    day = (
        calendar_date
        if isinstance(calendar_date, date)
        else date.fromisoformat(str(calendar_date)[:10])
    )
    prev_d = (
        None
        if prev_trading_day is None
        else (
            prev_trading_day
            if isinstance(prev_trading_day, date)
            else date.fromisoformat(str(prev_trading_day)[:10])
        )
    )
    next_d = (
        None
        if next_trading_day is None
        else (
            next_trading_day
            if isinstance(next_trading_day, date)
            else date.fromisoformat(str(next_trading_day)[:10])
        )
    )
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.trading_calendar (
                exchange_code, calendar_date, is_trading_day,
                prev_trading_day, next_trading_day
            ) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (exchange_code, calendar_date) DO UPDATE SET
                is_trading_day = EXCLUDED.is_trading_day
                    OR market.trading_calendar.is_trading_day,
                prev_trading_day = COALESCE(
                    EXCLUDED.prev_trading_day, market.trading_calendar.prev_trading_day
                ),
                next_trading_day = COALESCE(
                    EXCLUDED.next_trading_day, market.trading_calendar.next_trading_day
                )
            """,
            (exchange_code, day, is_trading_day, prev_d, next_d),
        )
    return True


def upsert_suspend(
    exchange_code: str,
    secu_code: str,
    suspend_from: date | str,
    *,
    suspend_to: date | str | None = None,
    reason: str = "",
    source_code: str = "sina",
) -> bool:
    inner = ensure_security(exchange_code, secu_code)
    if inner is None:
        return False
    start = (
        suspend_from
        if isinstance(suspend_from, date)
        else date.fromisoformat(str(suspend_from)[:10])
    )
    end = None
    if suspend_to is not None:
        end = (
            suspend_to
            if isinstance(suspend_to, date)
            else date.fromisoformat(str(suspend_to)[:10])
        )
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.suspend (
                inner_code, suspend_from, suspend_to, reason, source_code
            ) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (inner_code, suspend_from) DO UPDATE SET
                suspend_to = EXCLUDED.suspend_to,
                reason = EXCLUDED.reason,
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (inner, start, end, reason or "", source_code),
        )
    return True


def set_watermark(
    source_code: str,
    dataset: str,
    scope_key: str = "",
    *,
    watermark_ts: datetime | None = None,
    watermark_day: date | str | None = None,
    detail: dict | None = None,
) -> bool:
    day = None
    if watermark_day is not None:
        day = (
            watermark_day
            if isinstance(watermark_day, date)
            else date.fromisoformat(str(watermark_day)[:10])
        )
    conn = _connect()
    if conn is None:
        return False
    import json

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.ingest_watermark (
                source_code, dataset, scope_key,
                watermark_ts, watermark_day, detail, updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s::jsonb, NOW())
            ON CONFLICT (source_code, dataset, scope_key) DO UPDATE SET
                watermark_ts = COALESCE(EXCLUDED.watermark_ts, market.ingest_watermark.watermark_ts),
                watermark_day = COALESCE(EXCLUDED.watermark_day, market.ingest_watermark.watermark_day),
                detail = COALESCE(EXCLUDED.detail, market.ingest_watermark.detail),
                updated_at = NOW()
            """,
            (
                source_code,
                dataset,
                scope_key or "",
                watermark_ts,
                day,
                json.dumps(detail) if detail is not None else None,
            ),
        )
    return True


def get_watermark_day(source_code: str, dataset: str, scope_key: str = "") -> date | None:
    conn = _connect()
    if conn is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT watermark_day FROM market.ingest_watermark
            WHERE source_code=%s AND dataset=%s AND scope_key=%s
            """,
            (source_code, dataset, scope_key or ""),
        )
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def get_watermark(
    source_code: str, dataset: str, scope_key: str = ""
) -> dict[str, Any] | None:
    """返回 watermark_day / detail / updated_at；无行则 None。"""
    conn = _connect()
    if conn is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT watermark_day, detail, updated_at
            FROM market.ingest_watermark
            WHERE source_code=%s AND dataset=%s AND scope_key=%s
            """,
            (source_code, dataset, scope_key or ""),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "watermark_day": row[0],
        "detail": row[1] if isinstance(row[1], dict) else row[1],
        "updated_at": row[2],
    }


def daily_coverage_map(
    *,
    window_start: date | str,
) -> dict[tuple[str, str], dict[str, Any]]:
    """(exchange, secu_code) → {count, min_day, max_day}（窗口内日线）。"""
    start = (
        window_start
        if isinstance(window_start, date)
        else date.fromisoformat(str(window_start)[:10])
    )
    conn = _connect()
    if conn is None:
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.exchange_code, s.secu_code,
                   COUNT(b.trading_day)::int AS cnt,
                   MIN(b.trading_day) AS min_day,
                   MAX(b.trading_day) AS max_day
            FROM market.security s
            LEFT JOIN market.bar_daily b
              ON b.inner_code = s.inner_code
             AND b.trading_day >= %s
            WHERE s.exchange_code IN ('SSE', 'SZSE', 'BSE')
            GROUP BY s.exchange_code, s.secu_code
            """,
            (start,),
        )
        for ex, code, cnt, min_day, max_day in cur.fetchall():
            out[(str(ex), str(code))] = {
                "count": int(cnt or 0),
                "min_day": min_day,
                "max_day": max_day,
            }
    return out


def count_bar_daily() -> int | None:
    """整表 `market.bar_daily` 行数；库不可用时返回 None。"""
    conn = _connect()
    if conn is None:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*)::bigint FROM market.bar_daily")
        row = cur.fetchone()
    if not row:
        return 0
    return int(row[0] or 0)


def daily_bar_count(
    exchange_code: str,
    secu_code: str,
    *,
    window_start: date | str,
) -> dict[str, Any]:
    """单票窗口内日线覆盖。"""
    start = (
        window_start
        if isinstance(window_start, date)
        else date.fromisoformat(str(window_start)[:10])
    )
    inner = ensure_security(exchange_code, secu_code)
    if inner is None:
        return {"count": 0, "min_day": None, "max_day": None}
    conn = _connect()
    if conn is None:
        return {"count": 0, "min_day": None, "max_day": None}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)::int, MIN(trading_day), MAX(trading_day)
            FROM market.bar_daily
            WHERE inner_code=%s AND trading_day >= %s
            """,
            (inner, start),
        )
        row = cur.fetchone()
    if not row:
        return {"count": 0, "min_day": None, "max_day": None}
    return {"count": int(row[0] or 0), "min_day": row[1], "max_day": row[2]}


def ingest_sina_klines(
    exchange_code: str,
    secu_code: str,
    *,
    daily: list[dict[str, Any]] | None = None,
    minute: list[dict[str, Any]] | None = None,
    minute_period: str = "5m",
    name: str = "",
    source_code: str = "sina",
) -> dict[str, int]:
    """把新浪 K 线 JSON 行写入 bar_daily / bar_minute，并推进水位与日历。"""
    n_d = n_m = 0
    last_day: date | None = None
    for bar in daily or []:
        day_s = str(bar.get("day") or "")[:10]
        if len(day_s) < 10:
            continue
        if upsert_bar_daily(exchange_code, secu_code, day_s, bar, source_code=source_code, name=name):
            n_d += 1
            d = date.fromisoformat(day_s)
            last_day = d if last_day is None or d > last_day else last_day
            upsert_calendar_day(exchange_code, d, is_trading_day=True)

    for bar in minute or []:
        day_raw = str(bar.get("day") or "").strip()
        if not day_raw:
            continue
        try:
            # 新浪分钟：北京时间
            if " " in day_raw:
                naive = datetime.strptime(day_raw[:19], "%Y-%m-%d %H:%M:%S")
            else:
                naive = datetime.strptime(day_raw[:10], "%Y-%m-%d")
            local = naive.replace(tzinfo=SH)
            bar_time = local.astimezone(timezone.utc)
            trading_day = local.date()
        except ValueError:
            continue
        if upsert_bar_minute(
            exchange_code,
            secu_code,
            minute_period,
            bar_time,
            trading_day,
            bar,
            source_code=source_code,
            name=name,
        ):
            n_m += 1
            last_day = trading_day if last_day is None or trading_day > last_day else last_day
            upsert_calendar_day(exchange_code, trading_day, is_trading_day=True)

    scope = f"{exchange_code}:{secu_code}"
    if n_d:
        set_watermark(source_code, "bar_daily", scope, watermark_day=last_day, detail={"n": n_d})
    if n_m:
        set_watermark(
            source_code,
            f"bar_minute:{minute_period}",
            scope,
            watermark_day=last_day,
            detail={"n": n_m},
        )
    return {"daily": n_d, "minute": n_m}


def seed_calendar_weekdays(
    exchange_code: str,
    *,
    days_back: int = 400,
    days_forward: int = 30,
) -> int:
    """按工作日粗填交易日历（节假日日后由日线覆盖为确认交易日）。"""
    today = datetime.now(SH).date()
    start = today - timedelta(days=days_back)
    end = today + timedelta(days=days_forward)
    n = 0
    d = start
    while d <= end:
        # 周一=0 … 周日=6
        is_td = d.weekday() < 5
        if upsert_calendar_day(exchange_code, d, is_trading_day=is_td):
            n += 1
        d += timedelta(days=1)
    set_watermark(
        "manual",
        "calendar",
        exchange_code,
        watermark_day=today,
        detail={"seed": "weekdays", "n": n},
    )
    return n


def maybe_mark_suspend_from_quote(
    exchange_code: str,
    secu_code: str,
    *,
    name: str,
    volume: float | int | None,
    price: float | None,
) -> bool:
    """启发式：名称含停牌且无有效价时记一条当日停牌（可后续人工修正）。"""
    if "停牌" not in (name or ""):
        return False
    if price is not None and float(price) > 0 and volume is not None and float(volume) > 0:
        return False
    today = datetime.now(SH).date()
    return upsert_suspend(
        exchange_code,
        secu_code,
        today,
        reason="name_flag_停牌",
        source_code="sina",
    )
