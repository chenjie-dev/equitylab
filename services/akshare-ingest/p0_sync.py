"""akshare-ingest P0：日历 + 证券主数据 + 种子日线（未复权）。"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from equitylab_market import pg as pg_market
from equitylab_market.symbols import code6, cn_equity_exchange, map_index_exchange

import util

SOURCE = util.SOURCE
_DEFAULT_INDEX = "000001,399001,399006,000300,000016,000852"
_DEFAULT_STOCKS = "600519,000001,000002,300750,601318"
_DEFAULT_ETF = "510300,159915,512880,159919"


def _bar_start() -> str:
    raw = os.environ.get("AKSHARE_INGEST_BAR_START", "").strip()
    if raw:
        return raw[:10].replace("-", "")
    days = util.int_env("AKSHARE_INGEST_WINDOW_DAYS", 180)
    return (date.today() - timedelta(days=days)).strftime("%Y%m%d")


def _bar_end() -> str:
    return date.today().strftime("%Y%m%d")


def sync_calendar(ak: Any) -> int:
    df = util.call_ak(ak.tool_trade_date_hist_sina)
    rows = util.df_records(df)
    if not rows:
        # 回落：东财交易日
        df = util.call_ak(getattr(ak, "tool_trade_date_hist_em", lambda: None))
        rows = util.df_records(df)
    if not rows:
        print("akshare-ingest calendar empty", flush=True)
        return 0
    # sina 列多为 trade_date；全当交易日
    norm: list[dict[str, Any]] = []
    for r in rows:
        day = util.day_s(r.get("trade_date") or r.get("日期") or r.get("date"))
        if not day:
            continue
        norm.append({"trade_date": day, "is_trading_day": True})
    total = 0
    for ex in ("SSE", "SZSE", "BSE"):
        n = pg_market.apply_calendar_rows(ex, norm, source_code=SOURCE)
        total += n
        print(f"akshare-ingest calendar {ex} rows={n}", flush=True)
    return total


def sync_stock_meta(ak: Any) -> list[dict[str, str]]:
    limit = util.int_env("AKSHARE_INGEST_STOCK_LIMIT", 80)
    raw = os.environ.get("AKSHARE_INGEST_STOCK_CODES", "").strip() or _DEFAULT_STOCKS
    seeds = [code6(x.strip()) for x in raw.split(",") if code6(x.strip())]
    df = util.call_ak(ak.stock_info_a_code_name)
    by_code: dict[str, str] = {}
    for row in util.df_records(df):
        c = code6(str(row.get("code") or row.get("证券代码") or ""))
        if not c:
            continue
        name = str(row.get("name") or row.get("证券简称") or "")
        by_code[c] = name
    out: list[dict[str, str]] = []
    ordered = list(seeds)
    for c in by_code:
        if c not in ordered:
            ordered.append(c)
        if len(ordered) >= limit:
            break
    for c in ordered[:limit]:
        ex = cn_equity_exchange(c)
        name = by_code.get(c, "")
        if pg_market.ensure_security(ex, c, name=name, secu_category="stock"):
            out.append({"exchange": ex, "code": c, "name": name})
    print(f"akshare-ingest stock meta count={len(out)}", flush=True)
    pg_market.set_watermark(
        SOURCE, "security_stock", "", watermark_day=date.today(), detail={"n": len(out)}
    )
    return out


def sync_index_meta(ak: Any) -> list[dict[str, str]]:
    seed_raw = os.environ.get("AKSHARE_INGEST_INDEX_CODES", _DEFAULT_INDEX)
    seeds = [code6(x.strip()) or x.strip() for x in seed_raw.split(",") if x.strip()]
    out: list[dict[str, str]] = []
    spot = util.call_ak(ak.stock_zh_index_spot_em)
    name_by: dict[str, str] = {}
    for row in util.df_records(spot):
        c = code6(str(row.get("代码") or row.get("code") or ""))
        if c:
            name_by[c] = str(row.get("名称") or row.get("name") or "")
    for c in seeds:
        c6 = code6(c) or c
        ex = map_index_exchange("", code=c6)
        name = name_by.get(c6, "")
        if pg_market.ensure_security(ex, c6, name=name, secu_category="index"):
            out.append({"exchange": ex, "code": c6, "name": name})
    print(f"akshare-ingest index meta count={len(out)}", flush=True)
    pg_market.set_watermark(
        SOURCE, "security_index", "", watermark_day=date.today(), detail={"n": len(out)}
    )
    return out


def sync_etf_meta(ak: Any) -> list[dict[str, str]]:
    limit = util.int_env("AKSHARE_INGEST_ETF_BAR_LIMIT", 8)
    seed_raw = os.environ.get("AKSHARE_INGEST_ETF_CODES", _DEFAULT_ETF)
    seeds = [code6(x.strip()) for x in seed_raw.split(",") if code6(x.strip())]
    df = util.call_ak(ak.fund_etf_spot_em)
    name_by: dict[str, str] = {}
    for row in util.df_records(df):
        c = code6(str(row.get("代码") or row.get("code") or ""))
        if c:
            name_by[c] = str(row.get("名称") or row.get("name") or "")
    ordered = list(seeds)
    for c in name_by:
        if c not in ordered:
            ordered.append(c)
    out: list[dict[str, str]] = []
    for c in ordered[: max(1, limit)]:
        ex = cn_equity_exchange(c)
        name = name_by.get(c, "")
        if pg_market.ensure_security(ex, c, name=name, secu_category="etf"):
            out.append({"exchange": ex, "code": c, "name": name})
    print(f"akshare-ingest etf meta count={len(out)}", flush=True)
    pg_market.set_watermark(
        SOURCE, "security_etf", "", watermark_day=date.today(), detail={"n": len(out)}
    )
    return out


def sync_convert_meta(ak: Any) -> int:
    limit = util.int_env("AKSHARE_INGEST_CONVERT_META_LIMIT", 200)
    df = util.call_ak(ak.bond_zh_cov)
    if df is None:
        df = util.call_ak(getattr(ak, "bond_zh_hs_cov_spot", lambda: None))
    n = 0
    for i, row in enumerate(util.df_records(df)):
        if i >= limit:
            break
        c = code6(
            str(
                row.get("债券代码")
                or row.get("code")
                or row.get("债券代码")
                or row.get("可转债代码")
                or ""
            )
        )
        if not c:
            continue
        ex = cn_equity_exchange(c)
        name = str(row.get("债券简称") or row.get("name") or row.get("可转债简称") or "")
        if pg_market.ensure_security(ex, c, name=name, secu_category="convertible"):
            n += 1
    print(f"akshare-ingest convert meta count={n}", flush=True)
    pg_market.set_watermark(
        SOURCE, "security_convertible", "", watermark_day=date.today(), detail={"n": n}
    )
    return n


def _upsert_hist_bars(
    ak: Any,
    *,
    exchange: str,
    code: str,
    name: str,
    secu_category: str,
    kind: str,
) -> int:
    """日线：强制 adjust=''（未复权）；非空复权则拒写。"""
    start = _bar_start()
    end = _bar_end()
    rows_raw: list[dict[str, Any]] = []
    if kind == "stock":
        df = util.call_ak(
            ak.stock_zh_a_hist,
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="",
        )
        if df is None:
            pg_market.set_watermark(
                SOURCE,
                "bar_daily",
                f"{exchange}:{code}",
                watermark_day=date.today(),
                detail={"n": 0, "kind": kind, "note": "upstream_disconnect"},
            )
            return 0
        rows_raw = util.df_records(df)
    elif kind == "index":
        df = util.call_ak(
            ak.stock_zh_index_daily_em,
            symbol=f"{'sh' if exchange == 'SSE' else 'sz'}{code}",
        )
        if df is None:
            df = util.call_ak(
                getattr(ak, "index_zh_a_hist", lambda **k: None),
                symbol=code,
                period="daily",
                start_date=start,
                end_date=end,
            )
        rows_raw = util.df_records(df)
    elif kind == "etf":
        df = util.call_ak(
            ak.fund_etf_hist_em,
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="",
        )
        rows_raw = util.df_records(df)
    else:
        return 0

    written = 0
    for row in rows_raw:
        day = util.day_s(
            row.get("日期") or row.get("date") or row.get("trade_date")
        )
        if not day:
            continue
        bar = {
            "open": row.get("开盘") or row.get("open"),
            "high": row.get("最高") or row.get("high"),
            "low": row.get("最低") or row.get("low"),
            "close": row.get("收盘") or row.get("close"),
            "volume": row.get("成交量") or row.get("volume"),
            "amount": row.get("成交额") or row.get("amount"),
            "prev_close": row.get("前收盘") or row.get("prev_close"),
        }
        if pg_market.upsert_bar_daily(
            exchange,
            code,
            day,
            bar,
            source_code=SOURCE,
            name=name,
            secu_category=secu_category,
        ):
            written += 1
    if written:
        pg_market.set_watermark(
            SOURCE,
            "bar_daily",
            f"{exchange}:{code}",
            watermark_day=date.today(),
            detail={"n": written, "kind": kind, "adjust": ""},
        )
    return written


def sync_seed_bars(
    ak: Any,
    stocks: list[dict[str, str]],
    indexes: list[dict[str, str]],
    etfs: list[dict[str, str]],
) -> dict[str, int]:
    ix_lim = util.int_env("AKSHARE_INGEST_INDEX_BAR_LIMIT", 12)
    etf_lim = util.int_env("AKSHARE_INGEST_ETF_BAR_LIMIT", 8)
    stock_lim = util.int_env("AKSHARE_INGEST_STOCK_BAR_LIMIT", 20)
    totals = {"stock": 0, "index": 0, "etf": 0}
    for item in indexes[:ix_lim]:
        n = _upsert_hist_bars(
            ak,
            exchange=item["exchange"],
            code=item["code"],
            name=item.get("name") or "",
            secu_category="index",
            kind="index",
        )
        totals["index"] += n
        print(f"akshare-ingest index bar {item['exchange']}:{item['code']} n={n}", flush=True)
        util.sleep_ms()
    for item in etfs[:etf_lim]:
        n = _upsert_hist_bars(
            ak,
            exchange=item["exchange"],
            code=item["code"],
            name=item.get("name") or "",
            secu_category="etf",
            kind="etf",
        )
        totals["etf"] += n
        print(f"akshare-ingest etf bar {item['exchange']}:{item['code']} n={n}", flush=True)
        util.sleep_ms()
    for item in stocks[:stock_lim]:
        n = _upsert_hist_bars(
            ak,
            exchange=item["exchange"],
            code=item["code"],
            name=item.get("name") or "",
            secu_category="stock",
            kind="stock",
        )
        totals["stock"] += n
        print(f"akshare-ingest stock bar {item['exchange']}:{item['code']} n={n}", flush=True)
        util.sleep_ms()
    return totals


def run_p0(ak: Any, *, inc_sync: Callable[[str, str], None] | None = None) -> list[dict[str, str]]:
    def _inc(ds: str, st: str) -> None:
        if inc_sync:
            inc_sync(ds, st)

    try:
        n_cal = sync_calendar(ak)
        _inc("calendar", "ok" if n_cal else "empty")
    except Exception as exc:
        print(f"akshare-ingest p0 calendar failed: {exc}", flush=True)
        _inc("calendar", "fail")
        n_cal = 0
    stocks = sync_stock_meta(ak)
    indexes = sync_index_meta(ak)
    etfs = sync_etf_meta(ak)
    n_cv = sync_convert_meta(ak)
    bars = sync_seed_bars(ak, stocks, indexes, etfs)
    pg_market.set_watermark(
        SOURCE,
        "p0_round",
        "",
        watermark_ts=datetime.now(timezone.utc),
        detail={
            "calendar": n_cal,
            "stock_meta": len(stocks),
            "index_meta": len(indexes),
            "etf_meta": len(etfs),
            "convert_meta": n_cv,
            "bars": bars,
        },
    )
    print(
        f"akshare-ingest p0_done calendar={n_cal} stocks={len(stocks)} "
        f"indexes={len(indexes)} etfs={len(etfs)} convert={n_cv} bars={bars}",
        flush=True,
    )
    _inc("p0_round", "ok")
    return stocks
