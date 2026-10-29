"""akshare-ingest P2：资金流 + 财务核心。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from equitylab_market import pg as pg_market

import util

SOURCE = util.SOURCE


def sync_capital_flow(ak: Any, universe: list[dict[str, str]]) -> int:
    days = util.int_env("AKSHARE_INGEST_FLOW_DAYS", 60)
    end = date.today()
    start = end - timedelta(days=days)
    total = 0
    for item in universe:
        code = item["code"]
        ex = item["exchange"]
        # stock_fund_flow_individual 是排行接口（symbol=即时/3日…），禁止当个股回退
        if ex == "BSE":
            market = "bj"
        elif ex == "SSE":
            market = "sh"
        else:
            market = "sz"
        df = util.call_ak(
            ak.stock_individual_fund_flow,
            stock=code,
            market=market,
        )
        for row in util.df_records(df):
            day = util.day_s(row.get("日期") or row.get("date") or row.get("trade_date"))
            if not day:
                continue
            try:
                if date.fromisoformat(day) < start:
                    continue
            except ValueError:
                pass
            main = util.to_float(
                row.get("主力净流入-净额")
                or row.get("主力净流入")
                or row.get("main_net")
            )
            # 东财单位常为元；若绝对值很小可能是万元
            def _amt(v: float | None) -> float | None:
                if v is None:
                    return None
                if abs(v) < 1e6:
                    return v * 1e4
                return v

            if pg_market.upsert_capital_flow_daily(
                item["exchange"],
                code,
                day,
                main_net=_amt(main),
                super_large_net=_amt(
                    util.to_float(row.get("超大单净流入-净额") or row.get("超大单净流入"))
                ),
                large_net=_amt(
                    util.to_float(row.get("大单净流入-净额") or row.get("大单净流入"))
                ),
                medium_net=_amt(
                    util.to_float(row.get("中单净流入-净额") or row.get("中单净流入"))
                ),
                small_net=_amt(
                    util.to_float(row.get("小单净流入-净额") or row.get("小单净流入"))
                ),
                name=item.get("name") or "",
                source_code=SOURCE,
            ):
                total += 1
        print(f"akshare-ingest capital_flow {code}", flush=True)
        util.sleep_ms()
    if total:
        pg_market.set_watermark(
            SOURCE,
            "capital_flow_daily",
            "",
            watermark_day=date.today(),
            detail={"n": total},
        )
    return total


def sync_plate_flow(ak: Any) -> int:
    df = util.call_ak(ak.stock_fund_flow_concept, symbol="即时")
    if df is None:
        df = util.call_ak(ak.stock_fund_flow_concept, symbol="今日")
    rows = util.df_records(df)[: util.int_env("AKSHARE_INGEST_PLATE_FLOW_LIMIT", 40)]
    day = date.today().isoformat()
    total = 0
    for row in rows:
        name = str(row.get("行业") or row.get("名称") or row.get("概念") or "").strip()
        if not name:
            continue
        pcode = f"AK:{name[:28]}"
        pg_market.upsert_plate(
            "east", pcode, name=name, plate_kind="concept", source_code=SOURCE
        )
        main = util.to_float(row.get("今日主力净流入-净额") or row.get("主力净流入"))
        if main is not None and abs(main) < 1e8:
            main *= 1e4
        if pg_market.upsert_capital_flow_plate_daily(
            "east",
            pcode,
            day,
            main_net=main,
            plate_name=name,
            source_code=SOURCE,
        ):
            total += 1
    if total:
        pg_market.set_watermark(
            SOURCE,
            "capital_flow_plate_daily",
            "",
            watermark_day=date.today(),
            detail={"n": total},
        )
    print(f"akshare-ingest plate_flow n={total}", flush=True)
    return total


def sync_finance(ak: Any, universe: list[dict[str, str]]) -> int:
    report_lim = util.int_env("AKSHARE_INGEST_FINANCE_REPORT_LIMIT", 8)
    total = 0
    want = {
        "摊薄每股收益(元)": "basic_eps",
        "每股收益": "basic_eps",
        "净利润": "net_profit_attr_sh",
        "营业总收入": "total_rev",
        "净资产收益率": "roe_wtd",
        "销售毛利率": "gross_margin",
        "销售净利率": "net_margin",
        "资产负债率": "asset_liab_ratio",
    }
    for item in universe:
        code = item["code"]
        df = util.call_ak(ak.stock_financial_analysis_indicator, symbol=code)
        rows = util.df_records(df)
        # 宽表：日期列 + 指标列
        if not rows:
            util.sleep_ms()
            continue
        # 取最近 report_lim 行
        for row in rows[:report_lim]:
            report = util.day_s(
                row.get("日期") or row.get("报告期") or row.get("date")
            )
            if not report:
                continue
            for cn, code_i in want.items():
                if cn not in row and not any(cn in str(k) for k in row):
                    continue
                val = row.get(cn)
                if val is None:
                    for k, v in row.items():
                        if cn in str(k):
                            val = v
                            break
                if val is None:
                    continue
                name_map = {
                    "basic_eps": "基本每股收益",
                    "net_profit_attr_sh": "归母净利润",
                    "total_rev": "营业总收入",
                    "roe_wtd": "ROE",
                    "gross_margin": "毛利率",
                    "net_margin": "净利率",
                    "asset_liab_ratio": "资产负债率",
                }
                if pg_market.upsert_finance_core(
                    item["exchange"],
                    code,
                    report,
                    code_i,
                    value=util.to_float(val),
                    indicator_name=name_map.get(code_i, cn),
                    name=item.get("name") or "",
                    source_code=SOURCE,
                ):
                    total += 1
        print(f"akshare-ingest finance {code}", flush=True)
        util.sleep_ms()
    if total:
        pg_market.set_watermark(
            SOURCE, "finance_core", "", watermark_day=date.today(), detail={"n": total}
        )
    return total


def run_p2(
    ak: Any,
    universe: list[dict[str, str]],
    *,
    inc_sync: Callable[[str, str], None] | None = None,
) -> None:
    if util.env_flag("AKSHARE_INGEST_SKIP_P2", "0"):
        print("akshare-ingest p2 skip", flush=True)
        return

    def _inc(ds: str, st: str) -> None:
        if inc_sync:
            inc_sync(ds, st)

    for name, fn in (
        ("capital_flow_daily", lambda: sync_capital_flow(ak, universe)),
        ("capital_flow_plate_daily", lambda: sync_plate_flow(ak)),
        ("finance_core", lambda: sync_finance(ak, universe)),
    ):
        try:
            n = fn()
            _inc(name, "ok" if n else "empty")
        except Exception as exc:
            print(f"akshare-ingest p2 {name} failed: {exc}", flush=True)
            _inc(name, "fail")
    pg_market.set_watermark(
        SOURCE, "p2_round", "", watermark_day=date.today(), detail={"universe": len(universe)}
    )
    print("akshare-ingest p2_done", flush=True)
