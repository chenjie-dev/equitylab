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

本模块：日线 / 日历 / sina 覆盖 + P1–P3（板块/资金流/财务/舆情）写入辅助。
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
                  -- 日线 upsert 默认 category=stock，不得把已有 index/etf 降级
                  secu_category = CASE
                    WHEN EXCLUDED.secu_category = 'stock'
                      AND market.security.secu_category <> 'stock'
                    THEN market.security.secu_category
                    ELSE EXCLUDED.secu_category
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
    secu_category: str = "stock",
) -> bool:
    """写入 / 覆盖一根日线（交易所原始价）。"""
    inner = ensure_security(
        exchange_code, secu_code, name=name, secu_category=secu_category
    )
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


# P1 成分/行业「当前快照」统一生效日起点（上游常无调入日；重跑幂等）
_MEMBERSHIP_FROM = date(1990, 1, 1)


def _as_day(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def upsert_share_capital(
    exchange_code: str,
    secu_code: str,
    change_date: date | str,
    *,
    total_shares: Any = None,
    float_shares: Any = None,
    float_shares_a: Any = None,
    change_reason: str = "",
    name: str = "",
    source_code: str = "adata",
) -> bool:
    """写入 market.share_capital（单位：股）。"""
    inner = ensure_security(exchange_code, secu_code, name=name, secu_category="stock")
    if inner is None:
        return False
    day = _as_day(change_date)
    if day is None:
        return False
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.share_capital (
                inner_code, change_date, total_shares, float_shares, float_shares_a,
                change_reason, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (inner_code, change_date) DO UPDATE SET
                total_shares = COALESCE(EXCLUDED.total_shares, market.share_capital.total_shares),
                float_shares = COALESCE(EXCLUDED.float_shares, market.share_capital.float_shares),
                float_shares_a = COALESCE(EXCLUDED.float_shares_a, market.share_capital.float_shares_a),
                change_reason = CASE
                    WHEN EXCLUDED.change_reason <> '' THEN EXCLUDED.change_reason
                    ELSE market.share_capital.change_reason
                END,
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (
                inner,
                day,
                _dec(total_shares),
                _dec(float_shares),
                _dec(float_shares_a),
                change_reason or "",
                source_code,
            ),
        )
    return True


def upsert_industry_sw(
    industry_code: str,
    name: str,
    level: int,
    *,
    parent_code: str | None = None,
    source_code: str = "adata",
) -> bool:
    """写入 market.industry_sw；parent 须先存在或为空。"""
    code = (industry_code or "").strip()
    if not code or level not in (1, 2, 3):
        return False
    conn = _connect()
    if conn is None:
        return False
    parent = (parent_code or "").strip() or None
    with conn.cursor() as cur:
        if parent:
            # 父级占位，避免 FK 失败（名称可后续补）
            cur.execute(
                """
                INSERT INTO market.industry_sw (industry_code, name, level, parent_code, source_code)
                VALUES (%s, %s, %s, NULL, %s)
                ON CONFLICT (industry_code) DO NOTHING
                """,
                (parent, parent, max(1, level - 1), source_code),
            )
        cur.execute(
            """
            INSERT INTO market.industry_sw (
                industry_code, name, level, parent_code, source_code
            ) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (industry_code) DO UPDATE SET
                name = CASE
                    WHEN EXCLUDED.name <> '' AND EXCLUDED.name <> EXCLUDED.industry_code
                    THEN EXCLUDED.name ELSE market.industry_sw.name
                END,
                level = EXCLUDED.level,
                parent_code = COALESCE(EXCLUDED.parent_code, market.industry_sw.parent_code),
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (code, name or code, level, parent, source_code),
        )
    return True


def upsert_security_industry(
    exchange_code: str,
    secu_code: str,
    industry_code: str,
    *,
    effective_from: date | str | None = None,
    effective_to: date | str | None = None,
    name: str = "",
    source_code: str = "adata",
) -> bool:
    """证券↔申万归属；默认 effective_from=1990-01-01 表示当前快照。"""
    inner = ensure_security(exchange_code, secu_code, name=name, secu_category="stock")
    if inner is None:
        return False
    icode = (industry_code or "").strip()
    if not icode:
        return False
    start = _as_day(effective_from) or _MEMBERSHIP_FROM
    end = _as_day(effective_to)
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.security_industry (
                inner_code, industry_code, effective_from, effective_to, source_code
            ) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (inner_code, industry_code, effective_from) DO UPDATE SET
                effective_to = EXCLUDED.effective_to,
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (inner, icode, start, end, source_code),
        )
    return True


def upsert_plate(
    vendor: str,
    plate_code: str,
    *,
    name: str = "",
    plate_kind: str = "concept",
    link_security: bool = True,
    source_code: str = "adata",
) -> int | None:
    """写入 market.plate；可选挂 THS/EAST 概念 security，返回 plate 关联 inner_code。"""
    v = (vendor or "").strip().lower()
    code = (plate_code or "").strip()
    if v not in ("ths", "east") or not code:
        return None
    kind = (plate_kind or "concept").strip().lower()
    if kind not in ("concept", "industry", "region", "other"):
        kind = "other"
    exchange = "THS" if v == "ths" else "EAST"
    linked: int | None = None
    if link_security:
        linked = ensure_security(
            exchange, code, name=name or code, secu_category="concept"
        )
    conn = _connect()
    if conn is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.plate (
                vendor, plate_code, name, plate_kind, inner_code, source_code, updated_at
            ) VALUES (%s,%s,%s,%s,%s,%s, NOW())
            ON CONFLICT (vendor, plate_code) DO UPDATE SET
                name = CASE
                    WHEN EXCLUDED.name <> '' THEN EXCLUDED.name
                    ELSE market.plate.name
                END,
                plate_kind = EXCLUDED.plate_kind,
                inner_code = COALESCE(EXCLUDED.inner_code, market.plate.inner_code),
                source_code = EXCLUDED.source_code,
                updated_at = NOW()
            RETURNING inner_code
            """,
            (v, code, name or "", kind, linked, source_code),
        )
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else linked


def upsert_plate_member(
    vendor: str,
    plate_code: str,
    exchange_code: str,
    secu_code: str,
    *,
    effective_from: date | str | None = None,
    effective_to: date | str | None = None,
    name: str = "",
    source_code: str = "adata",
) -> bool:
    """板块成分；缺省 effective_from=1990-01-01。plate 行须已存在。"""
    v = (vendor or "").strip().lower()
    pcode = (plate_code or "").strip()
    if v not in ("ths", "east") or not pcode:
        return False
    # 确保 plate 目录行（无名称时至少占位）
    upsert_plate(v, pcode, name="", plate_kind="concept", source_code=source_code)
    inner = ensure_security(exchange_code, secu_code, name=name, secu_category="stock")
    if inner is None:
        return False
    start = _as_day(effective_from) or _MEMBERSHIP_FROM
    end = _as_day(effective_to)
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.plate_member (
                vendor, plate_code, inner_code, effective_from, effective_to, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (vendor, plate_code, inner_code, effective_from) DO UPDATE SET
                effective_to = EXCLUDED.effective_to,
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (v, pcode, inner, start, end, source_code),
        )
    return True


def upsert_index_member(
    index_exchange: str,
    index_code: str,
    member_exchange: str,
    member_code: str,
    *,
    effective_from: date | str | None = None,
    effective_to: date | str | None = None,
    weight: Any = None,
    index_name: str = "",
    member_name: str = "",
    source_code: str = "adata",
) -> bool:
    """指数成分（官方/权威）；与 plate_member 分离。"""
    idx = ensure_security(
        index_exchange, index_code, name=index_name, secu_category="index"
    )
    mem = ensure_security(
        member_exchange, member_code, name=member_name, secu_category="stock"
    )
    if idx is None or mem is None:
        return False
    start = _as_day(effective_from) or _MEMBERSHIP_FROM
    end = _as_day(effective_to)
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.index_member (
                index_inner_code, member_inner_code, effective_from, effective_to,
                weight, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (index_inner_code, member_inner_code, effective_from) DO UPDATE SET
                effective_to = EXCLUDED.effective_to,
                weight = COALESCE(EXCLUDED.weight, market.index_member.weight),
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (idx, mem, start, end, _dec(weight), source_code),
        )
    return True


def upsert_dividend(
    exchange_code: str,
    secu_code: str,
    ex_date: date | str,
    *,
    announce_date: date | str | None = None,
    record_date: date | str | None = None,
    pay_date: date | str | None = None,
    cash_per_share: Any = None,
    stock_per_share: Any = None,
    transfer_per_share: Any = None,
    remark: str = "",
    name: str = "",
    source_code: str = "adata",
) -> bool:
    """分红送转。announce 缺省时用 ex_date，满足 UNIQUE(inner, ex, announce)。"""
    inner = ensure_security(exchange_code, secu_code, name=name, secu_category="stock")
    if inner is None:
        return False
    ex = _as_day(ex_date)
    if ex is None:
        return False
    ann = _as_day(announce_date) or ex
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.dividend (
                inner_code, announce_date, ex_date, record_date, pay_date,
                cash_per_share, stock_per_share, transfer_per_share,
                remark, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (inner_code, ex_date, announce_date) DO UPDATE SET
                record_date = COALESCE(EXCLUDED.record_date, market.dividend.record_date),
                pay_date = COALESCE(EXCLUDED.pay_date, market.dividend.pay_date),
                cash_per_share = COALESCE(EXCLUDED.cash_per_share, market.dividend.cash_per_share),
                stock_per_share = COALESCE(
                    EXCLUDED.stock_per_share, market.dividend.stock_per_share
                ),
                transfer_per_share = COALESCE(
                    EXCLUDED.transfer_per_share, market.dividend.transfer_per_share
                ),
                remark = CASE
                    WHEN EXCLUDED.remark <> '' THEN EXCLUDED.remark
                    ELSE market.dividend.remark
                END,
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (
                inner,
                ann,
                ex,
                _as_day(record_date),
                _as_day(pay_date),
                _dec(cash_per_share),
                _dec(stock_per_share),
                _dec(transfer_per_share),
                remark or "",
                source_code,
            ),
        )
    return True


def upsert_capital_flow_daily(
    exchange_code: str,
    secu_code: str,
    trading_day: date | str,
    *,
    main_net: Any = None,
    super_large_net: Any = None,
    large_net: Any = None,
    medium_net: Any = None,
    small_net: Any = None,
    name: str = "",
    source_code: str = "adata",
) -> bool:
    """个股日度资金净流入（元）。"""
    inner = ensure_security(exchange_code, secu_code, name=name, secu_category="stock")
    if inner is None:
        return False
    day = _as_day(trading_day)
    if day is None:
        return False
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.capital_flow_daily (
                inner_code, trading_day, main_net, super_large_net, large_net,
                medium_net, small_net, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (inner_code, trading_day) DO UPDATE SET
                main_net = COALESCE(EXCLUDED.main_net, market.capital_flow_daily.main_net),
                super_large_net = COALESCE(
                    EXCLUDED.super_large_net, market.capital_flow_daily.super_large_net
                ),
                large_net = COALESCE(EXCLUDED.large_net, market.capital_flow_daily.large_net),
                medium_net = COALESCE(
                    EXCLUDED.medium_net, market.capital_flow_daily.medium_net
                ),
                small_net = COALESCE(EXCLUDED.small_net, market.capital_flow_daily.small_net),
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (
                inner,
                day,
                _dec(main_net),
                _dec(super_large_net),
                _dec(large_net),
                _dec(medium_net),
                _dec(small_net),
                source_code,
            ),
        )
    return True


def upsert_capital_flow_plate_daily(
    vendor: str,
    plate_code: str,
    trading_day: date | str,
    *,
    main_net: Any = None,
    super_large_net: Any = None,
    large_net: Any = None,
    medium_net: Any = None,
    small_net: Any = None,
    plate_name: str = "",
    plate_kind: str = "concept",
    source_code: str = "adata",
) -> bool:
    """板块日度资金净流入；自动确保 plate 行存在。"""
    v = (vendor or "").strip().lower()
    pcode = (plate_code or "").strip()
    if v not in ("ths", "east") or not pcode:
        return False
    day = _as_day(trading_day)
    if day is None:
        return False
    upsert_plate(
        v,
        pcode,
        name=plate_name,
        plate_kind=plate_kind,
        source_code=source_code,
    )
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.capital_flow_plate_daily (
                vendor, plate_code, trading_day, main_net, super_large_net,
                large_net, medium_net, small_net, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (vendor, plate_code, trading_day) DO UPDATE SET
                main_net = COALESCE(
                    EXCLUDED.main_net, market.capital_flow_plate_daily.main_net
                ),
                super_large_net = COALESCE(
                    EXCLUDED.super_large_net,
                    market.capital_flow_plate_daily.super_large_net
                ),
                large_net = COALESCE(
                    EXCLUDED.large_net, market.capital_flow_plate_daily.large_net
                ),
                medium_net = COALESCE(
                    EXCLUDED.medium_net, market.capital_flow_plate_daily.medium_net
                ),
                small_net = COALESCE(
                    EXCLUDED.small_net, market.capital_flow_plate_daily.small_net
                ),
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (
                v,
                pcode,
                day,
                _dec(main_net),
                _dec(super_large_net),
                _dec(large_net),
                _dec(medium_net),
                _dec(small_net),
                source_code,
            ),
        )
    return True


def upsert_finance_core(
    exchange_code: str,
    secu_code: str,
    report_date: date | str,
    indicator_code: str,
    *,
    value: Any = None,
    indicator_name: str = "",
    unit: str = "",
    name: str = "",
    source_code: str = "adata",
) -> bool:
    """核心财务指标长表一行。"""
    code = (indicator_code or "").strip()
    if not code:
        return False
    inner = ensure_security(exchange_code, secu_code, name=name, secu_category="stock")
    if inner is None:
        return False
    day = _as_day(report_date)
    if day is None:
        return False
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.finance_core (
                inner_code, report_date, indicator_code, indicator_name,
                value, unit, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (inner_code, report_date, indicator_code) DO UPDATE SET
                indicator_name = CASE
                    WHEN EXCLUDED.indicator_name <> '' THEN EXCLUDED.indicator_name
                    ELSE market.finance_core.indicator_name
                END,
                value = COALESCE(EXCLUDED.value, market.finance_core.value),
                unit = CASE
                    WHEN EXCLUDED.unit <> '' THEN EXCLUDED.unit
                    ELSE market.finance_core.unit
                END,
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (
                inner,
                day,
                code[:64],
                (indicator_name or "")[:128],
                _dec(value),
                unit or "",
                source_code,
            ),
        )
    return True


def upsert_lifting(
    exchange_code: str,
    secu_code: str,
    lift_date: date | str,
    *,
    shares: Any = None,
    ratio: Any = None,
    holder_type: str = "",
    remark: str = "",
    name: str = "",
    source_code: str = "adata",
) -> bool:
    """限售解禁；UNIQUE(inner, lift_date, holder_type, shares)。"""
    inner = ensure_security(exchange_code, secu_code, name=name, secu_category="stock")
    if inner is None:
        return False
    day = _as_day(lift_date)
    if day is None:
        return False
    conn = _connect()
    if conn is None:
        return False
    # UNIQUE 含 shares；NULL 在 PG 唯一约束中互不等价，缺省写 0
    sh = _dec(shares)
    if sh is None:
        sh = Decimal(0)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.lifting (
                inner_code, lift_date, shares, ratio, holder_type, remark, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (inner_code, lift_date, holder_type, shares) DO UPDATE SET
                ratio = COALESCE(EXCLUDED.ratio, market.lifting.ratio),
                remark = CASE
                    WHEN EXCLUDED.remark <> '' THEN EXCLUDED.remark
                    ELSE market.lifting.remark
                END,
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (inner, day, sh, _dec(ratio), holder_type or "", remark or "", source_code),
        )
    return True


def upsert_margin_balance(
    trading_day: date | str,
    *,
    market_scope: str = "CN",
    financing_balance: Any = None,
    securities_balance: Any = None,
    margin_balance: Any = None,
    source_code: str = "adata",
) -> bool:
    """两融余额日度。"""
    day = _as_day(trading_day)
    if day is None:
        return False
    scope = (market_scope or "CN").strip() or "CN"
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.margin_balance (
                trading_day, market_scope, financing_balance, securities_balance,
                margin_balance, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (trading_day, market_scope) DO UPDATE SET
                financing_balance = COALESCE(
                    EXCLUDED.financing_balance, market.margin_balance.financing_balance
                ),
                securities_balance = COALESCE(
                    EXCLUDED.securities_balance, market.margin_balance.securities_balance
                ),
                margin_balance = COALESCE(
                    EXCLUDED.margin_balance, market.margin_balance.margin_balance
                ),
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (
                day,
                scope[:32],
                _dec(financing_balance),
                _dec(securities_balance),
                _dec(margin_balance),
                source_code,
            ),
        )
    return True


def upsert_north_flow_daily(
    trading_day: date | str,
    *,
    net_flow: Any = None,
    buy_amount: Any = None,
    sell_amount: Any = None,
    sh_net: Any = None,
    sz_net: Any = None,
    source_code: str = "adata",
) -> bool:
    """北向资金日度。"""
    day = _as_day(trading_day)
    if day is None:
        return False
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.north_flow_daily (
                trading_day, net_flow, buy_amount, sell_amount, sh_net, sz_net, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (trading_day) DO UPDATE SET
                net_flow = COALESCE(EXCLUDED.net_flow, market.north_flow_daily.net_flow),
                buy_amount = COALESCE(
                    EXCLUDED.buy_amount, market.north_flow_daily.buy_amount
                ),
                sell_amount = COALESCE(
                    EXCLUDED.sell_amount, market.north_flow_daily.sell_amount
                ),
                sh_net = COALESCE(EXCLUDED.sh_net, market.north_flow_daily.sh_net),
                sz_net = COALESCE(EXCLUDED.sz_net, market.north_flow_daily.sz_net),
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (
                day,
                _dec(net_flow),
                _dec(buy_amount),
                _dec(sell_amount),
                _dec(sh_net),
                _dec(sz_net),
                source_code,
            ),
        )
    return True


def upsert_lhb_list(
    exchange_code: str,
    secu_code: str,
    trading_day: date | str,
    *,
    list_reason: str = "",
    close: Any = None,
    change_pct: Any = None,
    amount: Any = None,
    net_buy: Any = None,
    name: str = "",
    source_code: str = "adata",
) -> int | None:
    """龙虎榜上榜日；返回 lhb_list.id。"""
    inner = ensure_security(exchange_code, secu_code, name=name, secu_category="stock")
    if inner is None:
        return None
    day = _as_day(trading_day)
    if day is None:
        return None
    conn = _connect()
    if conn is None:
        return None
    reason = (list_reason or "")[:256]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.lhb_list (
                trading_day, inner_code, list_reason, close, change_pct,
                amount, net_buy, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (trading_day, inner_code, list_reason) DO UPDATE SET
                close = COALESCE(EXCLUDED.close, market.lhb_list.close),
                change_pct = COALESCE(EXCLUDED.change_pct, market.lhb_list.change_pct),
                amount = COALESCE(EXCLUDED.amount, market.lhb_list.amount),
                net_buy = COALESCE(EXCLUDED.net_buy, market.lhb_list.net_buy),
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            RETURNING id
            """,
            (
                day,
                inner,
                reason,
                _dec(close),
                _dec(change_pct),
                _dec(amount),
                _dec(net_buy),
                source_code,
            ),
        )
        row = cur.fetchone()
    return int(row[0]) if row else None


def upsert_lhb_detail(
    lhb_list_id: int,
    *,
    seat_name: str = "",
    side: str = "",
    buy_amount: Any = None,
    sell_amount: Any = None,
    net_amount: Any = None,
    source_code: str = "adata",
) -> bool:
    """龙虎榜席位明细；同 list+seat+side 先删后插保持幂等。"""
    if not lhb_list_id:
        return False
    side_n = (side or "").strip().lower()
    if side_n not in ("buy", "sell", "unknown", ""):
        side_n = "unknown"
    seat = (seat_name or "")[:256]
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM market.lhb_detail
            WHERE lhb_list_id=%s AND seat_name=%s AND side=%s
            """,
            (lhb_list_id, seat, side_n),
        )
        cur.execute(
            """
            INSERT INTO market.lhb_detail (
                lhb_list_id, seat_name, side, buy_amount, sell_amount,
                net_amount, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                lhb_list_id,
                seat,
                side_n,
                _dec(buy_amount),
                _dec(sell_amount),
                _dec(net_amount),
                source_code,
            ),
        )
    return True


def upsert_hot_rank_daily(
    trading_day: date | str,
    vendor: str,
    rank_type: str,
    rank_no: int,
    *,
    exchange_code: str | None = None,
    secu_code: str | None = None,
    plate_vendor: str | None = None,
    plate_code: str | None = None,
    name: str = "",
    score: Any = None,
    source_code: str = "adata",
) -> bool:
    """热度日终榜一行。"""
    day = _as_day(trading_day)
    if day is None:
        return False
    v = (vendor or "").strip().lower()
    if v not in ("ths", "east", "adata"):
        return False
    rtype = (rank_type or "").strip()[:32]
    if not rtype or int(rank_no) < 1:
        return False
    inner = None
    if exchange_code and secu_code:
        inner = ensure_security(
            exchange_code, secu_code, name=name, secu_category="stock"
        )
    pv = (plate_vendor or "").strip().lower() or None
    pc = (plate_code or "").strip() or None
    if pv and pc:
        upsert_plate(pv, pc, name=name, plate_kind="concept", source_code=source_code)
    conn = _connect()
    if conn is None:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO market.hot_rank_daily (
                trading_day, vendor, rank_type, rank_no, inner_code,
                plate_vendor, plate_code, name, score, source_code
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (trading_day, vendor, rank_type, rank_no) DO UPDATE SET
                inner_code = COALESCE(EXCLUDED.inner_code, market.hot_rank_daily.inner_code),
                plate_vendor = COALESCE(
                    EXCLUDED.plate_vendor, market.hot_rank_daily.plate_vendor
                ),
                plate_code = COALESCE(
                    EXCLUDED.plate_code, market.hot_rank_daily.plate_code
                ),
                name = CASE
                    WHEN EXCLUDED.name <> '' THEN EXCLUDED.name
                    ELSE market.hot_rank_daily.name
                END,
                score = COALESCE(EXCLUDED.score, market.hot_rank_daily.score),
                source_code = EXCLUDED.source_code,
                ingested_at = NOW()
            """,
            (
                day,
                v,
                rtype,
                int(rank_no),
                inner,
                pv,
                pc,
                name or "",
                _dec(score),
                source_code,
            ),
        )
    return True


def list_securities(
    *,
    secu_category: str | None = "stock",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """列出已入库证券（供采集族按目录扩写）。"""
    conn = _connect()
    if conn is None:
        return []
    lim = max(1, min(int(limit), 20000))
    with conn.cursor() as cur:
        if secu_category:
            cur.execute(
                """
                SELECT exchange_code, secu_code, name, secu_category
                FROM market.security
                WHERE secu_category = %s
                ORDER BY exchange_code, secu_code
                LIMIT %s
                """,
                (secu_category, lim),
            )
        else:
            cur.execute(
                """
                SELECT exchange_code, secu_code, name, secu_category
                FROM market.security
                ORDER BY exchange_code, secu_code
                LIMIT %s
                """,
                (lim,),
            )
        rows = cur.fetchall() or []
    return [
        {
            "exchange": r[0],
            "code": r[1],
            "name": r[2] or "",
            "secu_category": r[3],
        }
        for r in rows
    ]


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


def apply_calendar_rows(
    exchange_code: str,
    rows: list[dict[str, Any]],
    *,
    source_code: str = "adata",
) -> int:
    """按上游交易日历行写入 trading_calendar。

    每行至少含 calendar_date / trade_date / date；
    is_trading_day 缺省时看 trade_status / is_open（1/true/交易日）。
    """
    n = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw_day = (
            row.get("calendar_date")
            or row.get("trade_date")
            or row.get("date")
            or row.get("cal_date")
        )
        if not raw_day:
            continue
        day = (
            raw_day
            if isinstance(raw_day, date)
            else date.fromisoformat(str(raw_day)[:10])
        )
        flag = row.get("is_trading_day")
        if flag is None:
            flag = row.get("trade_status", row.get("is_open", row.get("is_trade_date")))
        if isinstance(flag, str):
            is_td = flag.strip().lower() in ("1", "true", "yes", "交易", "交易日", "open")
        elif flag is None:
            is_td = True
        else:
            is_td = bool(flag)
        if upsert_calendar_day(exchange_code, day, is_trading_day=is_td):
            n += 1
    if n:
        set_watermark(
            source_code,
            "calendar",
            exchange_code,
            watermark_day=datetime.now(SH).date(),
            detail={"n": n},
        )
    return n


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
