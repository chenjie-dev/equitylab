"""adata-ingest P3：舆情日终（解禁/两融/北向/龙虎榜/热度榜）。

分时北向/热度不进 market。ADATA_INGEST_SKIP_P3=1 可关。
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from equitylab_market import pg as pg_market
from equitylab_market.symbols import code6, map_adata_exchange

import eastmoney_lifting
import eastmoney_north

SOURCE = "adata"
SLEEP_MS = float(os.environ.get("ADATA_INGEST_SLEEP_MS", "300"))
SH = ZoneInfo("Asia/Shanghai")


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip() or default)
    except ValueError:
        return default


def _sleep() -> None:
    time.sleep(max(0.05, SLEEP_MS / 1000.0))


def _df_records(df: Any) -> list[dict[str, Any]]:
    if df is None:
        return []
    try:
        if getattr(df, "empty", False):
            return []
        return df.to_dict(orient="records")
    except Exception:
        return []


def _today() -> date:
    return datetime.now(SH).date()


def sync_lifting() -> int:
    try:
        rows = eastmoney_lifting.stock_lifting(
            max_pages=_int_env("ADATA_INGEST_LIFTING_PAGES", 10)
        )
    except Exception as exc:
        print(f"adata-ingest p3 lifting failed: {exc}", flush=True)
        return 0
    n = 0
    for row in rows:
        code = code6(str(row.get("stock_code") or ""))
        if not code:
            continue
        ex = map_adata_exchange("", code=code)
        if pg_market.upsert_lifting(
            ex,
            code,
            str(row.get("lift_date") or "")[:10],
            shares=row.get("shares"),
            ratio=row.get("ratio"),
            holder_type=str(row.get("holder_type") or ""),
            name=str(row.get("short_name") or ""),
            source_code=SOURCE,
        ):
            n += 1
    print(f"adata-ingest p3 lifting n={n}", flush=True)
    if n:
        pg_market.set_watermark(
            SOURCE, "lifting", "", watermark_day=_today(), detail={"n": n}
        )
    return n


def sync_margin(adata) -> int:
    start = os.environ.get("ADATA_INGEST_MARGIN_START", "").strip()
    if not start:
        start = (_today() - timedelta(days=_int_env("ADATA_INGEST_MARGIN_DAYS", 120))).isoformat()
    try:
        df = adata.sentiment.securities_margin(start_date=start)
    except Exception as exc:
        print(f"adata-ingest p3 margin failed: {exc}", flush=True)
        return 0
    n = 0
    for row in _df_records(df):
        day = row.get("trade_date") or row.get("trading_day")
        if not day:
            continue
        if pg_market.upsert_margin_balance(
            str(day)[:10],
            market_scope="CN",
            financing_balance=row.get("rzye"),
            securities_balance=row.get("rqye"),
            margin_balance=row.get("rzrqye"),
            source_code=SOURCE,
        ):
            n += 1
    print(f"adata-ingest p3 margin n={n} start={start}", flush=True)
    if n:
        pg_market.set_watermark(
            SOURCE,
            "margin_balance",
            "CN",
            watermark_day=_today(),
            detail={"n": n, "start": start},
        )
    return n


def sync_north_flow() -> int:
    try:
        rows = eastmoney_north.north_flow_daily(
            pages=_int_env("ADATA_INGEST_NORTH_PAGES", 8)
        )
    except Exception as exc:
        print(f"adata-ingest p3 north failed: {exc}", flush=True)
        return 0
    n = 0
    for row in rows:
        day = row.get("trade_date")
        if not day:
            continue
        if pg_market.upsert_north_flow_daily(
            str(day)[:10],
            net_flow=row.get("net_flow"),
            buy_amount=row.get("buy_amount"),
            sell_amount=row.get("sell_amount"),
            sh_net=row.get("sh_net"),
            sz_net=row.get("sz_net"),
            source_code=SOURCE,
        ):
            n += 1
    print(f"adata-ingest p3 north n={n}", flush=True)
    if n:
        pg_market.set_watermark(
            SOURCE, "north_flow_daily", "", watermark_day=_today(), detail={"n": n}
        )
    else:
        print(
            "adata-ingest p3 north empty "
            "(eastmoney NET_DEAL_AMT 近端常为 null，水位仍记尝试)",
            flush=True,
        )
        pg_market.set_watermark(
            SOURCE,
            "north_flow_daily",
            "",
            watermark_day=_today(),
            detail={"n": 0, "note": "net_fields_null"},
        )
    return n


def _lhb_dates() -> list[str]:
    raw = os.environ.get("ADATA_INGEST_LHB_DATES", "").strip()
    if raw:
        return [x.strip()[:10] for x in raw.split(",") if x.strip()]
    # 默认回溯若干自然日（跳过空榜）
    days = _int_env("ADATA_INGEST_LHB_LOOKBACK", 7)
    today = _today()
    return [(today - timedelta(days=i)).isoformat() for i in range(1, max(1, days) + 1)]


def sync_lhb(adata) -> dict[str, int]:
    detail_limit = _int_env("ADATA_INGEST_LHB_DETAIL_LIMIT", 15)
    n_list = 0
    n_detail = 0
    for day in _lhb_dates():
        try:
            df = adata.sentiment.hot.list_a_list_daily(report_date=day)
        except Exception as exc:
            print(f"adata-ingest p3 lhb {day} failed: {exc}", flush=True)
            continue
        rows = _df_records(df)
        if not rows:
            print(f"adata-ingest p3 lhb {day} empty", flush=True)
            continue
        for i, row in enumerate(rows):
            code = code6(str(row.get("stock_code") or ""))
            if not code:
                continue
            ex = map_adata_exchange("", code=code)
            reason = str(row.get("reason") or row.get("list_reason") or "")
            lid = pg_market.upsert_lhb_list(
                ex,
                code,
                day,
                list_reason=reason,
                close=row.get("close"),
                change_pct=row.get("change_cpt") or row.get("change_pct"),
                amount=row.get("amount"),
                net_buy=row.get("a_net_amount") or row.get("net_buy"),
                name=str(row.get("short_name") or ""),
                source_code=SOURCE,
            )
            if lid is None:
                continue
            n_list += 1
            if i >= detail_limit:
                continue
            try:
                info = adata.sentiment.hot.get_a_list_info(
                    stock_code=code, report_date=day
                )
            except Exception as exc:
                print(f"adata-ingest p3 lhb_detail {code} {day} failed: {exc}", flush=True)
                continue
            for drow in _df_records(info):
                buy = drow.get("a_buy_amount")
                sell = drow.get("a_sell_amount")
                side = "unknown"
                try:
                    b = float(buy or 0)
                    s = float(sell or 0)
                    if b > s:
                        side = "buy"
                    elif s > b:
                        side = "sell"
                except (TypeError, ValueError):
                    pass
                if pg_market.upsert_lhb_detail(
                    lid,
                    seat_name=str(drow.get("operate_name") or ""),
                    side=side,
                    buy_amount=buy,
                    sell_amount=sell,
                    net_amount=drow.get("a_net_amount"),
                    source_code=SOURCE,
                ):
                    n_detail += 1
            _sleep()
        print(f"adata-ingest p3 lhb {day} list_rows={len(rows)}", flush=True)
        _sleep()
    print(f"adata-ingest p3 lhb lists={n_list} details={n_detail}", flush=True)
    if n_list:
        pg_market.set_watermark(
            SOURCE,
            "lhb_list",
            "",
            watermark_day=_today(),
            detail={"list": n_list, "detail": n_detail},
        )
    return {"list": n_list, "detail": n_detail}


def sync_hot_ranks(adata) -> dict[str, int]:
    day = _today()
    # 非交易日仍记自然日快照
    out = {"pop_east": 0, "hot_ths": 0, "concept_ths": 0}

    for attempt in range(2):
        try:
            df = adata.sentiment.hot.pop_rank_100_east()
            for row in _df_records(df):
                code = code6(str(row.get("stock_code") or ""))
                if not code:
                    continue
                ex = map_adata_exchange("", code=code)
                rank = int(row.get("rank") or 0)
                if rank < 1:
                    continue
                if pg_market.upsert_hot_rank_daily(
                    day,
                    "east",
                    "pop100",
                    rank,
                    exchange_code=ex,
                    secu_code=code,
                    name=str(row.get("short_name") or ""),
                    score=row.get("change_pct"),
                    source_code=SOURCE,
                ):
                    out["pop_east"] += 1
            break
        except Exception as exc:
            print(
                f"adata-ingest p3 hot pop_east attempt={attempt} failed: {exc}",
                flush=True,
            )
            _sleep()

    try:
        df = adata.sentiment.hot.hot_rank_100_ths()
        for row in _df_records(df):
            code = code6(str(row.get("stock_code") or ""))
            if not code:
                continue
            ex = map_adata_exchange("", code=code)
            rank = int(row.get("rank") or 0)
            if rank < 1:
                continue
            if pg_market.upsert_hot_rank_daily(
                day,
                "ths",
                "hot_stock",
                rank,
                exchange_code=ex,
                secu_code=code,
                name=str(row.get("short_name") or ""),
                score=row.get("hot_value"),
                source_code=SOURCE,
            ):
                out["hot_ths"] += 1
    except Exception as exc:
        print(f"adata-ingest p3 hot ths failed: {exc}", flush=True)

    try:
        df = adata.sentiment.hot.hot_concept_20_ths(plate_type=1)
        for row in _df_records(df):
            pcode = str(row.get("concept_code") or "").strip()
            rank = int(row.get("rank") or 0)
            if not pcode or rank < 1:
                continue
            if pg_market.upsert_hot_rank_daily(
                day,
                "ths",
                "hot_concept",
                rank,
                plate_vendor="ths",
                plate_code=pcode,
                name=str(row.get("concept_name") or ""),
                score=row.get("hot_value"),
                source_code=SOURCE,
            ):
                out["concept_ths"] += 1
    except Exception as exc:
        print(f"adata-ingest p3 hot concept failed: {exc}", flush=True)

    total = sum(out.values())
    print(f"adata-ingest p3 hot_rank {out}", flush=True)
    if total:
        pg_market.set_watermark(
            SOURCE, "hot_rank_daily", "", watermark_day=day, detail=out
        )
    return out


def run_p3(adata, *, inc_sync: Callable[[str, str], None] | None = None) -> dict[str, Any]:
    if _env_flag("ADATA_INGEST_SKIP_P3", "0"):
        print("adata-ingest p3 skip=1", flush=True)
        return {"skipped": True}

    detail: dict[str, Any] = {}
    for name, fn in (
        ("lifting", sync_lifting),
        ("margin", lambda: sync_margin(adata)),
        ("north", sync_north_flow),
        ("lhb", lambda: sync_lhb(adata)),
        ("hot_rank", lambda: sync_hot_ranks(adata)),
    ):
        try:
            detail[name] = fn()
            if inc_sync:
                inc_sync(name, "ok")
        except Exception as exc:
            detail[name] = f"fail:{exc}"
            if inc_sync:
                inc_sync(name, "fail")
            print(f"adata-ingest p3 {name} failed: {exc}", flush=True)

    pg_market.set_watermark(
        SOURCE, "p3_round", "", watermark_day=_today(), detail=detail
    )
    print(f"adata-ingest p3_round_done {detail}", flush=True)
    return detail
