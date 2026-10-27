"""adata-ingest P2：个股/板块资金流 + finance_core。

分时资金流不进 market（→ qdb）。ADATA_INGEST_SKIP_P2=1 可关。
"""

from __future__ import annotations

import math
import os
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from equitylab_market import pg as pg_market

import eastmoney_capital_flow
import p1_sync

SOURCE = "adata"
SLEEP_MS = float(os.environ.get("ADATA_INGEST_SLEEP_MS", "300"))
SH = ZoneInfo("Asia/Shanghai")

# finance_core 宽表 → 长表时跳过的元数据列
_FIN_SKIP = frozenset(
    {
        "stock_code",
        "short_name",
        "report_date",
        "report_type",
        "notice_date",
    }
)

# 指标展示名（缺省用英文码）
_FIN_NAMES: dict[str, str] = {
    "basic_eps": "基本每股收益",
    "diluted_eps": "稀释每股收益",
    "non_gaap_eps": "扣非每股收益",
    "net_asset_ps": "每股净资产",
    "total_rev": "营业总收入",
    "gross_profit": "毛利润",
    "net_profit_attr_sh": "归母净利润",
    "non_gaap_net_profit": "扣非净利润",
    "roe_wtd": "加权ROE",
    "roa_wtd": "加权ROA",
    "gross_margin": "毛利率",
    "net_margin": "净利率",
    "asset_liab_ratio": "资产负债率",
    "curr_ratio": "流动比率",
    "quick_ratio": "速动比率",
}


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


def _is_nan(value: Any) -> bool:
    if value is None:
        return True
    try:
        if isinstance(value, float) and math.isnan(value):
            return True
    except Exception:
        pass
    s = str(value).strip().lower()
    return s in ("", "nan", "none", "null", "-")


def _flow_start() -> str | None:
    raw = os.environ.get("ADATA_INGEST_FLOW_START", "").strip()
    if raw:
        return raw[:10]
    days = _int_env("ADATA_INGEST_FLOW_DAYS", 60)
    return (date.today() - timedelta(days=max(1, days))).isoformat()


def sync_capital_flow_daily(adata, universe: list[dict[str, str]]) -> int:
    del adata  # 直调东财 push2his；保留参数对齐其它 sync_*
    start = _flow_start()
    total = 0
    for item in universe:
        code = item["code"]
        rows: list[dict[str, Any]] = []
        for attempt in range(2):
            try:
                rows = eastmoney_capital_flow.stock_capital_flow_daily(
                    item["exchange"], code, start_date=start
                )
            except Exception as exc:
                print(
                    f"adata-ingest p2 capital_flow {code} "
                    f"attempt={attempt} failed: {exc}",
                    flush=True,
                )
                rows = []
            if rows:
                break
            _sleep()
        n = 0
        for row in rows:
            day = row.get("trade_date") or row.get("trading_day")
            if not day:
                continue
            if pg_market.upsert_capital_flow_daily(
                item["exchange"],
                code,
                str(day)[:10],
                main_net=row.get("main_net_inflow"),
                super_large_net=row.get("max_net_inflow"),
                large_net=row.get("lg_net_inflow"),
                medium_net=row.get("mid_net_inflow"),
                small_net=row.get("sm_net_inflow"),
                name=item.get("name") or "",
                source_code=SOURCE,
            ):
                n += 1
        total += n
        print(f"adata-ingest p2 capital_flow {code} n={n}", flush=True)
        if n:
            pg_market.set_watermark(
                SOURCE,
                "capital_flow_daily",
                f"{item['exchange']}:{code}",
                watermark_day=date.today(),
                detail={"n": n, "start": start},
            )
        _sleep()
    return total


def sync_capital_flow_plate() -> int:
    """东财概念板块当日资金流快照 → capital_flow_plate_daily（trading_day=上海今日）。"""
    days_type = _int_env("ADATA_INGEST_PLATE_FLOW_DAYS_TYPE", 1)
    if days_type not in (1, 5, 10):
        days_type = 1
    rows: list[dict[str, Any]] = []
    for attempt in range(2):
        try:
            rows = eastmoney_capital_flow.plate_capital_flow(days_type=days_type)
        except Exception as exc:
            print(
                f"adata-ingest p2 plate_flow attempt={attempt} failed: {exc}",
                flush=True,
            )
            rows = []
        if rows:
            break
        _sleep()
    today = datetime.now(SH).date()
    n = 0
    for row in rows:
        pcode = str(row.get("plate_code") or row.get("index_code") or "").strip()
        if not pcode:
            continue
        if pg_market.upsert_capital_flow_plate_daily(
            "east",
            pcode,
            today,
            main_net=row.get("main_net_inflow"),
            super_large_net=row.get("max_net_inflow"),
            large_net=row.get("lg_net_inflow"),
            medium_net=row.get("mid_net_inflow"),
            small_net=row.get("sm_net_inflow"),
            plate_name=str(row.get("plate_name") or row.get("index_name") or ""),
            plate_kind="concept",
            source_code=SOURCE,
        ):
            n += 1
    print(
        f"adata-ingest p2 plate_flow days_type={days_type} n={n} day={today}",
        flush=True,
    )
    if n:
        pg_market.set_watermark(
            SOURCE,
            "capital_flow_plate_daily",
            f"east:d{days_type}",
            watermark_day=today,
            detail={"n": n, "days_type": days_type},
        )
    return n


def sync_finance_core(adata, universe: list[dict[str, str]]) -> int:
    """get_core_index 宽表拆成长表；ADATA_INGEST_FINANCE_REPORT_LIMIT 限制最近报告期数。"""
    report_limit = _int_env("ADATA_INGEST_FINANCE_REPORT_LIMIT", 8)
    total = 0
    for item in universe:
        code = item["code"]
        try:
            df = adata.stock.finance.get_core_index(stock_code=code)
        except Exception as exc:
            print(f"adata-ingest p2 finance {code} failed: {exc}", flush=True)
            continue
        rows = _df_records(df)
        # 按报告期倒序截断
        def _rd(r: dict[str, Any]) -> str:
            return str(r.get("report_date") or "")[:10]

        rows = sorted(rows, key=_rd, reverse=True)[: max(1, report_limit)]
        n = 0
        for row in rows:
            rd = row.get("report_date")
            if not rd:
                continue
            name = str(row.get("short_name") or item.get("name") or "")
            for key, val in row.items():
                if key in _FIN_SKIP or _is_nan(val):
                    continue
                try:
                    float(val)
                except (TypeError, ValueError):
                    continue
                if pg_market.upsert_finance_core(
                    item["exchange"],
                    code,
                    str(rd)[:10],
                    str(key),
                    value=val,
                    indicator_name=_FIN_NAMES.get(str(key), ""),
                    name=name,
                    source_code=SOURCE,
                ):
                    n += 1
        total += n
        print(f"adata-ingest p2 finance {code} indicators={n} reports={len(rows)}", flush=True)
        if n:
            pg_market.set_watermark(
                SOURCE,
                "finance_core",
                f"{item['exchange']}:{code}",
                watermark_day=date.today(),
                detail={"n": n, "reports": len(rows)},
            )
        _sleep()
    return total


def run_p2(adata, *, inc_sync: Callable[[str, str], None] | None = None) -> dict[str, Any]:
    if _env_flag("ADATA_INGEST_SKIP_P2", "0"):
        print("adata-ingest p2 skip=1", flush=True)
        return {"skipped": True}

    # 与 P1 共用股票面上限；可单独 ADATA_INGEST_P2_STOCK_LIMIT
    limit_backup = os.environ.get("ADATA_INGEST_STOCK_LIMIT")
    p2_lim = os.environ.get("ADATA_INGEST_P2_STOCK_LIMIT", "").strip()
    if p2_lim:
        os.environ["ADATA_INGEST_STOCK_LIMIT"] = p2_lim
    try:
        universe = p1_sync.stock_universe()
    finally:
        if p2_lim:
            if limit_backup is None:
                os.environ.pop("ADATA_INGEST_STOCK_LIMIT", None)
            else:
                os.environ["ADATA_INGEST_STOCK_LIMIT"] = limit_backup

    detail: dict[str, Any] = {"universe": len(universe)}
    print(f"adata-ingest p2 universe n={len(universe)}", flush=True)

    for name, fn in (
        ("capital_flow_daily", lambda: sync_capital_flow_daily(adata, universe)),
        ("capital_flow_plate", sync_capital_flow_plate),
        ("finance_core", lambda: sync_finance_core(adata, universe)),
    ):
        try:
            detail[name] = fn()
            if inc_sync:
                inc_sync(name, "ok")
        except Exception as exc:
            detail[name] = f"fail:{exc}"
            if inc_sync:
                inc_sync(name, "fail")
            print(f"adata-ingest p2 {name} failed: {exc}", flush=True)

    pg_market.set_watermark(
        SOURCE, "p2_round", "", watermark_day=date.today(), detail=detail
    )
    print(f"adata-ingest p2_round_done {detail}", flush=True)
    return detail
