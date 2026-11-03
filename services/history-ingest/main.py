"""授权回源边车：A 股冷历史多周期回补 + 宇宙目录刷新。

边界（docs/market/2026-10-26-行情模块边界.md）：
- 本进程可访问上游；写 market.bar_daily / bar_minute（冷），默认不写 qdb trades。
- 维护 qdb docs `cn-equity:codes`（collector 默认 skip A 股盘中后由本进程刷新）。
- 分钟默认 5m/15m/60m 短窗；不做全市场 1m / 半年硬灌。
"""

from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from equitylab_market import cn_universe, pg as pg_market
from equitylab_market.pg import normalize_bar_period
from equitylab_market.sina import daily_klines as sina_daily_klines
from equitylab_market.sina import minute_klines as sina_minute_klines
from equitylab_market.symbols import cn_equity_exchange, code6, is_cn_listed_equity
from equitylab_qdb import Client

CODES_DOC_KEY = cn_universe.CODES_DOC_KEY
SOURCE = "sina"
COVERAGE_DAILY = "bar_daily_coverage"

WINDOW_DAYS = int(os.environ.get("HISTORY_INGEST_WINDOW_DAYS", "180"))
MIN_BARS = int(os.environ.get("HISTORY_INGEST_MIN_BARS", "100"))
DAILY_DATALEN = int(os.environ.get("HISTORY_INGEST_DATALEN", "200"))
SLEEP_MS = float(os.environ.get("HISTORY_INGEST_SLEEP_MS", "400"))
IDLE_SEC = float(os.environ.get("HISTORY_INGEST_IDLE_SEC", "30"))
BATCH_FILL = int(os.environ.get("HISTORY_INGEST_BATCH", "50"))
FAIL_TTL_SEC = float(os.environ.get("HISTORY_INGEST_FAIL_TTL_SEC", "1800"))
EXHAUSTED_TTL_SEC = float(
    os.environ.get("HISTORY_INGEST_EXHAUSTED_TTL_SEC", str(7 * 24 * 3600))
)
PARTIAL_TTL_SEC = float(
    os.environ.get("HISTORY_INGEST_PARTIAL_TTL_SEC", str(6 * 3600))
)
MAX_PER_ROUND = int(os.environ.get("HISTORY_INGEST_MAX_PER_ROUND", "200"))

# 分钟多周期：短窗覆盖，默认不做半年硬灌
MINUTE_WINDOW_DAYS = int(os.environ.get("HISTORY_INGEST_MINUTE_WINDOW_DAYS", "40"))
MINUTE_DATALEN = int(os.environ.get("HISTORY_INGEST_MINUTE_DATALEN", "500"))
MINUTE_MIN_BARS = int(os.environ.get("HISTORY_INGEST_MINUTE_MIN_BARS", "80"))
MINUTE_SKIP = os.environ.get("HISTORY_INGEST_MINUTE_SKIP", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _parse_minute_periods() -> list[str]:
    raw = (
        os.environ.get("HISTORY_INGEST_MINUTE_PERIODS") or "5m,15m,60m"
    ).strip()
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.replace(";", ",").split(","):
        p = part.strip().lower()
        if not p or p in ("1d", "daily"):
            continue
        store = normalize_bar_period(p)
        # 对外仍用请求名；水位用 store（60m→1h）
        key = store
        if key in seen:
            continue
        if key not in ("1m", "5m", "15m", "30m", "1h"):
            continue
        # 不存 30m 物理表（读面折叠 15m）；跳过 1m 除非显式配置
        if key == "30m":
            continue
        if key == "1m" and "1m" not in raw.lower():
            continue
        seen.add(key)
        # 写入用产品名：1h 用 60m 拉新浪亦可
        out.append("60m" if key == "1h" else key)
    return out or ["5m", "15m", "60m"]


MINUTE_PERIODS = _parse_minute_periods()

qdb = Client(timeout=15.0)


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _coverage_dataset_minute(period: str) -> str:
    store = normalize_bar_period(period)
    return f"bar_minute:{store}_coverage"


def load_universe() -> list[dict[str, str]]:
    """从 qdb cn-equity:codes 取全表；失败则用 PG security。"""
    rows: list[dict[str, str]] = []
    try:
        body = qdb.get_doc(CODES_DOC_KEY)
    except Exception as exc:
        print(f"history-ingest codes doc failed: {exc}", flush=True)
        body = None
    value = body
    if isinstance(body, dict) and isinstance(body.get("value"), dict):
        value = body["value"]
    codes = (value or {}).get("codes") if isinstance(value, dict) else None
    if isinstance(codes, list):
        for item in codes:
            if not isinstance(item, dict):
                continue
            c = code6(str(item.get("code") or item.get("stock_code") or ""))
            if not c or not is_cn_listed_equity(c):
                continue
            ex_raw = str(item.get("exchange") or "").upper()
            if ex_raw not in ("SSE", "SZSE", "BSE"):
                ex_raw = cn_equity_exchange(c)
            name = str(item.get("name") or item.get("short_name") or "")
            rows.append({"exchange": ex_raw, "code": c, "name": name})

    if rows:
        seen: set[str] = set()
        out: list[dict[str, str]] = []
        for r in rows:
            k = f"{r['exchange']}:{r['code']}"
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    cov = pg_market.daily_coverage_map(window_start=date(2000, 1, 1))
    return [
        {"exchange": ex, "code": code, "name": ""}
        for (ex, code) in sorted(cov.keys())
        if is_cn_listed_equity(code)
    ]


def refresh_codes_doc() -> int:
    """新浪 hs_a → qdb cn-equity:codes；返回宇宙只数。"""
    seed = cn_universe.seed_codes_from_env()
    rows, doc = cn_universe.resolve_universe(seed=seed)
    qdb.put_docs(cn_universe.codes_doc_items(doc))
    print(
        f"history-ingest codes published count={doc.get('count')} "
        f"source={doc.get('source')} mode={doc.get('universe')}",
        flush=True,
    )
    return int(doc.get("count") or len(rows))


def refresh_codes_doc_retry(*, attempts: int = 12, delay_s: float = 5.0) -> int:
    """启动期 qdb 可能尚未就绪：短重试。"""
    last: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            if not qdb.wait_ready(timeout=3.0):
                raise RuntimeError("qdb not ready")
            return refresh_codes_doc()
        except Exception as exc:
            last = exc
            print(
                f"history-ingest codes publish retry {i + 1}/{attempts}: {exc}",
                flush=True,
            )
            time.sleep(delay_s)
    raise RuntimeError(f"codes publish failed after retries: {last}")


def _codes_refresh_worker() -> None:
    """定期刷新；qdb 清卷导致 docs 丢失时立刻补写，不等满刷新间隔。"""
    while True:
        try:
            missing = True
            try:
                doc = qdb.get_doc(CODES_DOC_KEY)
                missing = not (isinstance(doc, dict) and doc.get("codes"))
            except Exception:
                missing = True
            if not missing:
                time.sleep(cn_universe.universe_refresh_sec())
            n = refresh_codes_doc()
            if missing:
                print(
                    f"history-ingest codes heal after missing doc count={n}",
                    flush=True,
                )
                time.sleep(30)
        except Exception as exc:
            print(f"history-ingest codes refresh failed: {exc}", flush=True)
            time.sleep(60)


def _in_backoff(dataset: str, scope: str) -> bool:
    row = pg_market.get_watermark(SOURCE, dataset, scope)
    if not row or not row.get("updated_at"):
        return False
    detail = row.get("detail") or {}
    if not isinstance(detail, dict):
        return False
    status = detail.get("status")
    if status == "fail":
        ttl = FAIL_TTL_SEC
    elif status == "partial":
        ttl = PARTIAL_TTL_SEC
    elif status == "exhausted":
        ttl = EXHAUSTED_TTL_SEC
    else:
        return False
    updated = row["updated_at"]
    if not isinstance(updated, datetime):
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds()
    return age < ttl


def pick_gaps(
    universe: list[dict[str, str]],
    coverage: dict[tuple[str, str], dict[str, Any]],
    *,
    dataset: str,
    min_bars: int,
    limit: int,
    seed_first: bool = True,
) -> list[dict[str, Any]]:
    seed_set = set(cn_universe.seed_codes_from_env()) if seed_first else set()
    gaps: list[dict[str, Any]] = []
    for item in universe:
        ex, code = item["exchange"], item["code"]
        if not is_cn_listed_equity(code):
            continue
        cov = coverage.get((ex, code)) or {"count": 0, "min_day": None, "max_day": None}
        cnt = int(cov.get("count") or 0)
        scope = f"{ex}:{code}"
        if cnt >= min_bars:
            continue
        if _in_backoff(dataset, scope):
            continue
        gaps.append(
            {
                "exchange": ex,
                "code": code,
                "name": item.get("name") or "",
                "count": cnt,
                "min_day": cov.get("min_day"),
                "max_day": cov.get("max_day"),
                "scope": scope,
                "_seed": 0 if code in seed_set else 1,
            }
        )
    # seed 优先，再按覆盖从少到多
    gaps.sort(key=lambda g: (int(g.get("_seed") or 1), int(g["count"])))
    return gaps[: max(1, limit)]


def fill_daily(gap: dict[str, Any], *, window_start: date) -> dict[str, Any]:
    ex, code, name = gap["exchange"], gap["code"], gap.get("name") or ""
    scope = gap["scope"]
    daily = sina_daily_klines(code, DAILY_DATALEN)
    stats = pg_market.ingest_sina_klines(
        ex, code, daily=daily, minute=None, name=name, source_code=SOURCE
    )
    after = pg_market.daily_bar_count(ex, code, window_start=window_start)
    cnt = int(after.get("count") or 0)
    written = int(stats.get("daily") or 0)
    if cnt >= MIN_BARS:
        status = "ok"
    elif written > 0 and cnt == 0:
        status = "exhausted"
    elif written == 0:
        status = "exhausted"
    elif written > 0 and cnt < MIN_BARS:
        status = "partial"
    else:
        status = "fail"
    pg_market.set_watermark(
        SOURCE,
        COVERAGE_DAILY,
        scope,
        watermark_day=after.get("max_day") or date.today(),
        watermark_ts=datetime.now(timezone.utc),
        detail={
            "status": status,
            "count": cnt,
            "written": written,
            "min_bars": MIN_BARS,
        },
    )
    return {
        "scope": scope,
        "period": "1d",
        "written": written,
        "count": cnt,
        "ok": status == "ok",
        "status": status,
    }


def fill_minute(
    gap: dict[str, Any],
    *,
    period: str,
    window_start: date,
) -> dict[str, Any]:
    ex, code, name = gap["exchange"], gap["code"], gap.get("name") or ""
    scope = gap["scope"]
    dataset = _coverage_dataset_minute(period)
    minute = sina_minute_klines(code, period, MINUTE_DATALEN, exchange=ex)
    stats = pg_market.ingest_sina_klines(
        ex,
        code,
        daily=None,
        minute=minute,
        minute_period=period,
        name=name,
        source_code=SOURCE,
    )
    after = pg_market.minute_bar_count(
        ex, code, period, window_start=window_start
    )
    cnt = int(after.get("count") or 0)
    written = int(stats.get("minute") or 0)
    if cnt >= MINUTE_MIN_BARS:
        status = "ok"
    elif written > 0 and cnt == 0:
        status = "exhausted"
    elif written == 0:
        status = "exhausted"
    elif written > 0 and cnt < MINUTE_MIN_BARS:
        status = "partial"
    else:
        status = "fail"
    pg_market.set_watermark(
        SOURCE,
        dataset,
        scope,
        watermark_day=after.get("max_day") or date.today(),
        watermark_ts=datetime.now(timezone.utc),
        detail={
            "status": status,
            "count": cnt,
            "written": written,
            "min_bars": MINUTE_MIN_BARS,
            "period": normalize_bar_period(period),
        },
    )
    return {
        "scope": scope,
        "period": normalize_bar_period(period),
        "written": written,
        "count": cnt,
        "ok": status == "ok",
        "status": status,
    }


def wait_ready() -> None:
    if not pg_market.enabled():
        raise SystemExit("history-ingest: DATABASE_URL required")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if qdb.wait_ready(timeout=5.0):
            if pg_market.daily_coverage_map(window_start=date.today()) is not None:
                return
        time.sleep(2)
    print("history-ingest: qdb/pg not ready, continuing anyway", flush=True)


def _run_gap_batch(
    *,
    label: str,
    gaps: list[dict[str, Any]],
    fill_fn: Any,
    pm: Any,
) -> int:
    filled = 0
    for gap in gaps:
        try:
            result = fill_fn(gap)
            filled += 1
            pm.inc_fill(str(result.get("status") or "unknown"))
            print(
                f"history-ingest fill={label} {result['scope']} "
                f"period={result.get('period')} written={result['written']} "
                f"count={result['count']} status={result.get('status')}",
                flush=True,
            )
        except Exception as exc:
            pm.inc_fill("fail")
            print(
                f"history-ingest fill_fail {label} {gap.get('scope')}: {exc}",
                flush=True,
            )
            try:
                dataset = (
                    COVERAGE_DAILY
                    if label == "1d"
                    else _coverage_dataset_minute(str(gap.get("_period") or "5m"))
                )
                pg_market.set_watermark(
                    SOURCE,
                    dataset,
                    gap["scope"],
                    watermark_ts=datetime.now(timezone.utc),
                    detail={"status": "fail", "error": str(exc)[:200]},
                )
            except Exception:
                pass
        time.sleep(max(0.05, SLEEP_MS / 1000.0))
    return filled


def main() -> None:
    import prom_metrics as pm

    pm.start_metrics_server()
    pm.heartbeat_loop()

    if _env_flag("HISTORY_INGEST_SKIP", "0"):
        pm.set_skip(True)
        print("history-ingest skipped (HISTORY_INGEST_SKIP=1)", flush=True)
        while True:
            time.sleep(3600)

    pm.set_skip(False)
    wait_ready()

    try:
        refresh_codes_doc_retry()
    except Exception as exc:
        print(f"history-ingest initial codes publish failed: {exc}", flush=True)
    threading.Thread(
        target=_codes_refresh_worker, name="history-codes", daemon=True
    ).start()

    window_start = date.today() - timedelta(days=WINDOW_DAYS)
    minute_window_start = date.today() - timedelta(days=MINUTE_WINDOW_DAYS)
    print(
        f"history-ingest start window_days={WINDOW_DAYS} min_bars={MIN_BARS} "
        f"sleep_ms={SLEEP_MS} batch={BATCH_FILL} datalen={DAILY_DATALEN} "
        f"minute_periods={MINUTE_PERIODS if not MINUTE_SKIP else 'skip'} "
        f"minute_window_days={MINUTE_WINDOW_DAYS} minute_datalen={MINUTE_DATALEN}",
        flush=True,
    )

    round_n = 0
    while True:
        t0 = time.monotonic()
        round_n += 1
        try:
            universe = load_universe()
            coverage = pg_market.daily_coverage_map(window_start=window_start)
            ok_n = 0
            for item in universe:
                cov = coverage.get((item["exchange"], item["code"])) or {}
                if int(cov.get("count") or 0) >= MIN_BARS:
                    ok_n += 1
            gaps = pick_gaps(
                universe,
                coverage,
                dataset=COVERAGE_DAILY,
                min_bars=MIN_BARS,
                limit=MAX_PER_ROUND,
            )
            pm.set_cover(
                universe=len(universe), ok=ok_n, gaps=len(gaps), round_n=round_n
            )
            try:
                pm.set_bar_daily_rows(pg_market.count_bar_daily())
            except Exception as exc:
                print(f"history-ingest bar_daily_count failed: {exc}", flush=True)
            print(
                f"history-ingest cover= round={round_n} universe={len(universe)} "
                f"ok={ok_n} gaps_queued={len(gaps)} window_start={window_start}",
                flush=True,
            )

            filled = _run_gap_batch(
                label="1d",
                gaps=gaps[:BATCH_FILL],
                fill_fn=lambda g, ws=window_start: fill_daily(g, window_start=ws),
                pm=pm,
            )

            if not MINUTE_SKIP:
                for period in MINUTE_PERIODS:
                    dataset = _coverage_dataset_minute(period)
                    m_cov = pg_market.minute_coverage_map(
                        period, window_start=minute_window_start
                    )
                    m_gaps = pick_gaps(
                        universe,
                        m_cov,
                        dataset=dataset,
                        min_bars=MINUTE_MIN_BARS,
                        limit=min(BATCH_FILL, MAX_PER_ROUND),
                    )
                    for g in m_gaps:
                        g["_period"] = period
                    print(
                        f"history-ingest minute={period} gaps={len(m_gaps)} "
                        f"window_start={minute_window_start}",
                        flush=True,
                    )
                    filled += _run_gap_batch(
                        label=period,
                        gaps=m_gaps,
                        fill_fn=lambda g, p=period, ws=minute_window_start: fill_minute(
                            g, period=p, window_start=ws
                        ),
                        pm=pm,
                    )

            elapsed = time.monotonic() - t0
            if not gaps and (MINUTE_SKIP or filled == 0):
                print(
                    f"history-ingest idle round={round_n} ok={ok_n}/{len(universe)} "
                    f"sleep={IDLE_SEC}s",
                    flush=True,
                )
                time.sleep(IDLE_SEC)
            else:
                print(
                    f"history-ingest round_done={round_n} filled={filled} "
                    f"elapsed_s={elapsed:.1f}",
                    flush=True,
                )
                time.sleep(min(IDLE_SEC, 5.0))
            window_start = date.today() - timedelta(days=WINDOW_DAYS)
            minute_window_start = date.today() - timedelta(days=MINUTE_WINDOW_DAYS)
        except Exception as exc:
            print(f"history-ingest round_failed: {exc}", flush=True)
            time.sleep(IDLE_SEC)


if __name__ == "__main__":
    main()
