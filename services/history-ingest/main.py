"""授权回源边车：持续扫描 Postgres market 日线覆盖，缺口从新浪补近半年。

边界（docs/market/2026-10-26-行情模块边界.md）：
- 本进程可访问上游；只写 market（冷），默认不写 qdb trades。
- 与盘中 collector 解耦，避免拖垮报价热循环。
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from equitylab_market import pg as pg_market
from equitylab_market.sina import daily_klines as sina_daily_klines
from equitylab_market.symbols import cn_equity_exchange, code6
from equitylab_qdb import Client

CODES_DOC_KEY = "cn-equity:codes"
COVERAGE_DATASET = "bar_daily_coverage"
SOURCE = "sina"

# 半年自然日窗口；达标阈值约 100 根交易日（半年≈120）
WINDOW_DAYS = int(os.environ.get("HISTORY_INGEST_WINDOW_DAYS", "180"))
MIN_BARS = int(os.environ.get("HISTORY_INGEST_MIN_BARS", "100"))
DAILY_DATALEN = int(os.environ.get("HISTORY_INGEST_DATALEN", "200"))
SLEEP_MS = float(os.environ.get("HISTORY_INGEST_SLEEP_MS", "400"))
IDLE_SEC = float(os.environ.get("HISTORY_INGEST_IDLE_SEC", "30"))
BATCH_FILL = int(os.environ.get("HISTORY_INGEST_BATCH", "50"))
FAIL_TTL_SEC = float(os.environ.get("HISTORY_INGEST_FAIL_TTL_SEC", "1800"))
# 上游有数但不在窗口内（退市/停更）：长退避，避免空转打上游
EXHAUSTED_TTL_SEC = float(os.environ.get("HISTORY_INGEST_EXHAUSTED_TTL_SEC", str(7 * 24 * 3600)))
MAX_PER_ROUND = int(os.environ.get("HISTORY_INGEST_MAX_PER_ROUND", "200"))

qdb = Client(timeout=15.0)


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def load_universe() -> list[dict[str, str]]:
    """从 qdb cn-equity:codes 取全表；失败则用 PG security。"""
    rows: list[dict[str, str]] = []
    try:
        body = qdb.get_doc(CODES_DOC_KEY)
        value = body
        if isinstance(body, dict) and isinstance(body.get("value"), dict):
            value = body["value"]
        codes = (value or {}).get("codes") if isinstance(value, dict) else None
        if isinstance(codes, list):
            for item in codes:
                if not isinstance(item, dict):
                    continue
                c = code6(str(item.get("code") or item.get("stock_code") or ""))
                if not c:
                    continue
                ex_raw = str(item.get("exchange") or "").upper()
                if ex_raw not in ("SSE", "SZSE", "BSE"):
                    ex_raw = cn_equity_exchange(c)
                name = str(item.get("name") or item.get("short_name") or "")
                rows.append({"exchange": ex_raw, "code": c, "name": name})
    except Exception as exc:
        print(f"history-ingest codes doc failed: {exc}", flush=True)

    if rows:
        # 去重保序
        seen: set[str] = set()
        out: list[dict[str, str]] = []
        for r in rows:
            k = f"{r['exchange']}:{r['code']}"
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    # 回落：已有 security 行
    cov = pg_market.daily_coverage_map(window_start=date(2000, 1, 1))
    return [
        {"exchange": ex, "code": code, "name": ""}
        for (ex, code) in sorted(cov.keys())
    ]


def _in_backoff(scope: str) -> bool:
    """fail 短退避 / exhausted 长退避。"""
    row = pg_market.get_watermark(SOURCE, COVERAGE_DATASET, scope)
    if not row or not row.get("updated_at"):
        return False
    detail = row.get("detail") or {}
    if not isinstance(detail, dict):
        return False
    status = detail.get("status")
    if status == "fail":
        ttl = FAIL_TTL_SEC
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
    limit: int,
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for item in universe:
        ex, code = item["exchange"], item["code"]
        cov = coverage.get((ex, code)) or {"count": 0, "min_day": None, "max_day": None}
        cnt = int(cov.get("count") or 0)
        scope = f"{ex}:{code}"
        if cnt >= MIN_BARS:
            continue
        if _in_backoff(scope):
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
            }
        )
    gaps.sort(key=lambda g: g["count"])
    return gaps[: max(1, limit)]


def fill_one(gap: dict[str, Any]) -> dict[str, Any]:
    ex, code, name = gap["exchange"], gap["code"], gap.get("name") or ""
    scope = gap["scope"]
    daily = sina_daily_klines(code, DAILY_DATALEN)
    stats = pg_market.ingest_sina_klines(
        ex, code, daily=daily, minute=None, name=name, source_code=SOURCE
    )
    after = pg_market.daily_bar_count(
        ex, code, window_start=date.today() - timedelta(days=WINDOW_DAYS)
    )
    cnt = int(after.get("count") or 0)
    written = int(stats.get("daily") or 0)
    if cnt >= MIN_BARS:
        status = "ok"
    elif written > 0 and cnt == 0:
        # 上游返回了棒但不在覆盖窗口（常见：退市/长期停更）
        status = "exhausted"
    elif written == 0:
        status = "fail"
    else:
        status = "fail"  # 写了但仍不足 MIN_BARS：短退避后再试
    pg_market.set_watermark(
        SOURCE,
        COVERAGE_DATASET,
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
            # 探测 PG
            if pg_market.daily_coverage_map(window_start=date.today()) is not None:
                return
        time.sleep(2)
    print("history-ingest: qdb/pg not ready, continuing anyway", flush=True)


def main() -> None:
    if _env_flag("HISTORY_INGEST_SKIP", "0"):
        print("history-ingest skipped (HISTORY_INGEST_SKIP=1)", flush=True)
        while True:
            time.sleep(3600)

    wait_ready()
    window_start = date.today() - timedelta(days=WINDOW_DAYS)
    print(
        f"history-ingest start window_days={WINDOW_DAYS} min_bars={MIN_BARS} "
        f"sleep_ms={SLEEP_MS} batch={BATCH_FILL} datalen={DAILY_DATALEN}",
        flush=True,
    )

    round_n = 0
    while True:
        t0 = time.monotonic()
        round_n += 1
        try:
            universe = load_universe()
            coverage = pg_market.daily_coverage_map(window_start=window_start)
            # 统计达标
            ok_n = 0
            for item in universe:
                cov = coverage.get((item["exchange"], item["code"])) or {}
                if int(cov.get("count") or 0) >= MIN_BARS:
                    ok_n += 1
            gaps = pick_gaps(universe, coverage, limit=MAX_PER_ROUND)
            print(
                f"history-ingest cover= round={round_n} universe={len(universe)} "
                f"ok={ok_n} gaps_queued={len(gaps)} window_start={window_start}",
                flush=True,
            )
            filled = 0
            for i, gap in enumerate(gaps):
                if i >= BATCH_FILL and filled == 0:
                    # 仍继续本轮至 MAX，但日志分段
                    pass
                try:
                    result = fill_one(gap)
                    filled += 1
                    print(
                        f"history-ingest fill= {result['scope']} "
                        f"written={result['written']} count={result['count']} "
                        f"status={result.get('status')} ok={result['ok']}",
                        flush=True,
                    )
                except Exception as exc:
                    print(
                        f"history-ingest fill_fail {gap.get('scope')}: {exc}",
                        flush=True,
                    )
                    try:
                        pg_market.set_watermark(
                            SOURCE,
                            COVERAGE_DATASET,
                            gap["scope"],
                            watermark_ts=datetime.now(timezone.utc),
                            detail={"status": "fail", "error": str(exc)[:200]},
                        )
                    except Exception:
                        pass
                time.sleep(max(0.05, SLEEP_MS / 1000.0))

            elapsed = time.monotonic() - t0
            if not gaps:
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
                # 仍有缺口：短休后继续
                time.sleep(min(IDLE_SEC, 5.0))
            # 刷新窗口起点（跨日）
            window_start = date.today() - timedelta(days=WINDOW_DAYS)
        except Exception as exc:
            print(f"history-ingest round_failed: {exc}", flush=True)
            time.sleep(IDLE_SEC)


if __name__ == "__main__":
    main()
