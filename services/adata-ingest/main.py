"""授权回源边车：adata → market（P0 日历/指数·ETF·可转债日线 + P1 板块/成分/股本/申万/分红）。

边界（docs/market/2026-10-26-行情模块边界.md + 2026-10-27-market-schema-adata完整域.md）：
- 可访问上游（adata SDK / 东财 push2）；只写 Postgres market；不写 qdb。
- 产品面仍是 cn-equity；source_code=adata；vendor=ths|east 仅作 plate 隔离。
- P2+（资金流/财务/舆情）另开。ADATA_INGEST_SKIP_P1=1 可跳过 P1。
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from equitylab_market import pg as pg_market
from equitylab_market.symbols import code6, map_adata_exchange, map_index_exchange

import eastmoney_bars
import p1_sync

SOURCE = "adata"
SLEEP_MS = float(os.environ.get("ADATA_INGEST_SLEEP_MS", "300"))
IDLE_SEC = float(os.environ.get("ADATA_INGEST_IDLE_SEC", "3600"))
BAR_START = os.environ.get("ADATA_INGEST_BAR_START", "").strip()  # YYYY-MM-DD；空=近 WINDOW 天
WINDOW_DAYS = int(os.environ.get("ADATA_INGEST_WINDOW_DAYS", "180"))
INDEX_BAR_LIMIT = int(os.environ.get("ADATA_INGEST_INDEX_BAR_LIMIT", "12"))
ETF_BAR_LIMIT = int(os.environ.get("ADATA_INGEST_ETF_BAR_LIMIT", "8"))
CONVERT_META_LIMIT = int(os.environ.get("ADATA_INGEST_CONVERT_META_LIMIT", "500"))

# 指数日线优先种子（可被 ADATA_INGEST_INDEX_CODES 覆盖，逗号分隔）
_DEFAULT_INDEX = "000001,399001,399006,000300,000016,000852,000905,399005"


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _bar_start() -> str:
    if BAR_START:
        return BAR_START[:10]
    return (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()


def _df_records(df: Any) -> list[dict[str, Any]]:
    if df is None:
        return []
    try:
        if getattr(df, "empty", False):
            return []
        return df.to_dict(orient="records")
    except Exception:
        return []


def _import_adata():
    import adata  # noqa: WPS433 — 可选重依赖，仅本服务安装

    return adata


def sync_calendar(adata) -> int:
    """深交所交易日历写入 SSE/SZSE/BSE（同一自然日规则）。"""
    total = 0
    try:
        df = adata.stock.info.trade_calendar()
    except Exception as exc:
        print(f"adata-ingest calendar fetch failed: {exc}", flush=True)
        return 0
    rows = _df_records(df)
    if not rows:
        print("adata-ingest calendar empty", flush=True)
        return 0
    for ex in ("SSE", "SZSE", "BSE"):
        n = pg_market.apply_calendar_rows(ex, rows, source_code=SOURCE)
        total += n
        print(f"adata-ingest calendar {ex} rows={n}", flush=True)
    return total


def sync_index_meta(adata) -> list[dict[str, str]]:
    """指数代码 → security(category=index)；返回可用于拉日线的列表。"""
    out: list[dict[str, str]] = []
    try:
        df = adata.stock.info.all_index_code()
    except Exception as exc:
        print(f"adata-ingest index meta failed: {exc}", flush=True)
        return out
    for row in _df_records(df):
        raw = str(
            row.get("index_code")
            or row.get("stock_code")
            or row.get("code")
            or ""
        )
        c = code6(raw) or "".join(ch for ch in raw if ch.isdigit() or ch.isalpha())[:16]
        if not c:
            continue
        # 指数：勿用个股前缀（000001=上证指数 → SSE）
        digits = code6(c)
        if digits:
            ex = map_index_exchange(str(row.get("exchange") or ""), code=digits)
            code = digits
        else:
            ex = "SSE"
            code = c.upper()
        name = str(row.get("short_name") or row.get("name") or row.get("index_name") or "")
        if pg_market.ensure_security(ex, code, name=name, secu_category="index"):
            out.append({"exchange": ex, "code": code, "name": name})
        time.sleep(max(0.0, SLEEP_MS / 1000.0 / 50.0))
    print(f"adata-ingest index meta count={len(out)}", flush=True)
    pg_market.set_watermark(
        SOURCE, "security_index", "", watermark_day=date.today(), detail={"n": len(out)}
    )
    return out


def sync_etf_meta(adata) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    try:
        df = adata.fund.info.all_etf_exchange_traded_info()
    except Exception as exc:
        print(f"adata-ingest etf meta failed: {exc}", flush=True)
        return out
    for row in _df_records(df):
        c = code6(
            str(row.get("fund_code") or row.get("stock_code") or row.get("code") or "")
        )
        if not c:
            continue
        ex = map_adata_exchange(str(row.get("exchange") or ""), code=c)
        name = str(row.get("short_name") or row.get("name") or row.get("fund_name") or "")
        if pg_market.ensure_security(ex, c, name=name, secu_category="etf"):
            out.append({"exchange": ex, "code": c, "name": name})
    print(f"adata-ingest etf meta count={len(out)}", flush=True)
    pg_market.set_watermark(
        SOURCE, "security_etf", "", watermark_day=date.today(), detail={"n": len(out)}
    )
    return out


def sync_convert_meta(adata) -> int:
    n = 0
    try:
        df = adata.bond.info.all_convert_code()
    except Exception as exc:
        print(f"adata-ingest convert meta failed: {exc}", flush=True)
        return 0
    for i, row in enumerate(_df_records(df)):
        if i >= CONVERT_META_LIMIT:
            break
        c = code6(
            str(
                row.get("bond_code")
                or row.get("stock_code")
                or row.get("code")
                or ""
            )
        )
        if not c:
            continue
        ex = map_adata_exchange(str(row.get("exchange") or ""), code=c)
        name = str(row.get("short_name") or row.get("name") or row.get("bond_name") or "")
        if pg_market.ensure_security(ex, c, name=name, secu_category="convertible"):
            n += 1
    print(f"adata-ingest convert meta count={n}", flush=True)
    pg_market.set_watermark(
        SOURCE, "security_convertible", "", watermark_day=date.today(), detail={"n": n}
    )
    return n


def _upsert_bars(
    exchange: str,
    code: str,
    *,
    name: str,
    rows: list[dict[str, Any]],
    secu_category: str,
) -> int:
    written = 0
    for row in rows:
        day = row.get("trade_date") or row.get("trade_time") or row.get("date")
        if day is None:
            continue
        day_s = str(day)[:10]
        if pg_market.upsert_bar_daily(
            exchange,
            code,
            day_s,
            row,
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
            detail={"n": written},
        )
    return written


def sync_index_bars(meta: list[dict[str, str]]) -> int:
    """指数日线：东方财富 push2his（绕过 MiniRacer/THS）。"""
    seed_raw = os.environ.get("ADATA_INGEST_INDEX_CODES", _DEFAULT_INDEX)
    seed = {x.strip() for x in seed_raw.split(",") if x.strip()}
    by_code = {m["code"]: m for m in meta}
    targets: list[dict[str, str]] = []
    for c in seed:
        c6 = code6(c) or c
        if c6 in by_code:
            targets.append(by_code[c6])
        else:
            ex = map_index_exchange("", code=c6) if code6(c6) else "SSE"
            targets.append({"exchange": ex, "code": c6, "name": ""})
    targets = targets[: max(1, INDEX_BAR_LIMIT)]
    start = _bar_start()
    total = 0
    for item in targets:
        code = item["code"]
        try:
            rows = eastmoney_bars.daily_klines(
                item["exchange"], code, start_date=start
            )
        except Exception as exc:
            print(f"adata-ingest index bar {code} failed: {exc}", flush=True)
            continue
        n = _upsert_bars(
            item["exchange"],
            code,
            name=item.get("name") or "",
            rows=rows,
            secu_category="index",
        )
        total += n
        print(
            f"adata-ingest index bar {item['exchange']}:{code} written={n}",
            flush=True,
        )
        time.sleep(max(0.05, SLEEP_MS / 1000.0))
    return total


def sync_etf_bars(meta: list[dict[str, str]]) -> int:
    """ETF 日线：东方财富 push2his（同指数；避免 THS hexin-v）。"""
    if not meta:
        return 0
    start = _bar_start()
    total = 0
    for item in meta[: max(1, ETF_BAR_LIMIT)]:
        code = item["code"]
        try:
            rows = eastmoney_bars.daily_klines(
                item["exchange"], code, start_date=start
            )
        except Exception as exc:
            print(f"adata-ingest etf bar {code} failed: {exc}", flush=True)
            continue
        n = _upsert_bars(
            item["exchange"],
            code,
            name=item.get("name") or "",
            rows=rows,
            secu_category="etf",
        )
        total += n
        print(f"adata-ingest etf bar {item['exchange']}:{code} written={n}", flush=True)
        time.sleep(max(0.05, SLEEP_MS / 1000.0))
    return total


def run_round(adata) -> None:
    import prom_metrics as pm

    n_cal = sync_calendar(adata)
    indexes = sync_index_meta(adata)
    etfs = sync_etf_meta(adata)
    n_cv = sync_convert_meta(adata)
    n_ix = sync_index_bars(indexes)
    n_etf = sync_etf_bars(etfs)
    pg_market.set_watermark(
        SOURCE,
        "p0_round",
        "",
        watermark_ts=datetime.now(timezone.utc),
        detail={
            "calendar": n_cal,
            "index_meta": len(indexes),
            "etf_meta": len(etfs),
            "convert_meta": n_cv,
            "index_bars": n_ix,
            "etf_bars": n_etf,
        },
    )
    print(
        f"adata-ingest round_done calendar={n_cal} index_meta={len(indexes)} "
        f"etf_meta={len(etfs)} convert={n_cv} index_bars={n_ix} etf_bars={n_etf}",
        flush=True,
    )
    p1_sync.run_p1(adata, inc_sync=pm.inc_sync)


def main() -> None:
    import prom_metrics as pm

    pm.start_metrics_server()
    pm.heartbeat_loop()
    if _env_flag("ADATA_INGEST_SKIP", "0"):
        pm.set_skip(True)
        print("adata-ingest skip=1 idle", flush=True)
        while True:
            time.sleep(3600)
    pm.set_skip(False)
    if not pg_market.enabled():
        print("adata-ingest DATABASE_URL missing; exit", flush=True)
        return
    print(
        f"adata-ingest start window_days={WINDOW_DAYS} bar_start={_bar_start()} "
        f"index_bar_limit={INDEX_BAR_LIMIT} etf_bar_limit={ETF_BAR_LIMIT}",
        flush=True,
    )
    adata = _import_adata()
    round_n = 0
    while True:
        round_n += 1
        pm.set_round(round_n)
        try:
            run_round(adata)
            pm.inc_sync("p0_round", "ok")
        except Exception as exc:
            pm.inc_sync("p0_round", "fail")
            print(f"adata-ingest round_failed: {exc}", flush=True)
        time.sleep(max(60.0, IDLE_SEC))


if __name__ == "__main__":
    main()
