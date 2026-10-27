"""akshare-ingest P3：解禁 / 两融 / 北向 / 龙虎榜 / 热榜。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from equitylab_market import pg as pg_market
from equitylab_market.symbols import code6, cn_equity_exchange

import util

SOURCE = util.SOURCE


def sync_lifting(ak: Any) -> int:
    df = util.call_ak(ak.stock_restricted_release_detail_em)
    if df is None:
        df = util.call_ak(getattr(ak, "stock_restricted_release_queue_em", lambda: None))
    total = 0
    for row in util.df_records(df)[: util.int_env("AKSHARE_INGEST_LIFTING_LIMIT", 200)]:
        c = code6(str(row.get("代码") or row.get("股票代码") or row.get("code") or ""))
        if not c:
            continue
        day = util.day_s(
            row.get("解禁时间") or row.get("解禁日期") or row.get("lift_date")
        )
        if not day:
            continue
        shares = util.to_float(row.get("解禁数量") or row.get("解禁股数"))
        if shares is not None and abs(shares) < 1e6:
            shares *= 1e4  # 常见「万股」
        ratio = util.to_float(row.get("占总股本比例") or row.get("占比"))
        if pg_market.upsert_lifting(
            cn_equity_exchange(c),
            c,
            day,
            shares=shares,
            ratio=ratio,
            holder_type=str(row.get("解禁股东类型") or row.get("股东类型") or ""),
            name=str(row.get("名称") or row.get("股票简称") or ""),
            source_code=SOURCE,
        ):
            total += 1
    if total:
        pg_market.set_watermark(
            SOURCE, "lifting", "", watermark_day=date.today(), detail={"n": total}
        )
    print(f"akshare-ingest lifting n={total}", flush=True)
    return total


def sync_margin(ak: Any) -> int:
    days = util.int_env("AKSHARE_INGEST_MARGIN_DAYS", 120)
    start = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    total = 0
    # 上交所
    df_sh = util.call_ak(ak.stock_margin_sse, start_date=start, end_date=date.today().strftime("%Y%m%d"))
    for row in util.df_records(df_sh):
        day = util.day_s(row.get("信用交易日期") or row.get("日期") or row.get("date"))
        if not day:
            continue
        fin = util.to_float(row.get("融资余额") or row.get("融资余额(元)"))
        sec = util.to_float(row.get("融券余量金额") or row.get("融券余额"))
        if fin is not None and abs(fin) < 1e10:
            pass  # 已是元或亿元需判断
        if pg_market.upsert_margin_balance(
            day,
            market_scope="SSE",
            financing_balance=fin,
            securities_balance=sec,
            margin_balance=(fin or 0) + (sec or 0) if fin is not None or sec is not None else None,
            source_code=SOURCE,
        ):
            total += 1
    df_sz = util.call_ak(ak.stock_margin_szse, date=date.today().strftime("%Y%m%d"))
    # szse 常为单日快照序列；尝试近期
    for row in util.df_records(df_sz)[:5]:
        day = util.day_s(row.get("日期") or row.get("信用交易日期") or date.today())
        fin = util.to_float(row.get("融资余额") or row.get("融资余额(元)"))
        sec = util.to_float(row.get("融券余额") or row.get("融券余量金额"))
        if pg_market.upsert_margin_balance(
            day or date.today().isoformat(),
            market_scope="SZSE",
            financing_balance=fin,
            securities_balance=sec,
            margin_balance=(fin or 0) + (sec or 0) if fin is not None or sec is not None else None,
            source_code=SOURCE,
        ):
            total += 1
    # 全市场汇总账户信息（若有）
    df_acc = util.call_ak(ak.stock_margin_account_info)
    for row in util.df_records(df_acc)[: days]:
        day = util.day_s(row.get("日期") or row.get("date"))
        if not day:
            continue
        fin = util.to_float(row.get("融资余额") or row.get("融资余额(亿元)"))
        if fin is not None and abs(fin) < 1e6:
            fin *= 1e8  # 亿元 → 元
        sec = util.to_float(row.get("融券余额") or row.get("融券余量金额"))
        if sec is not None and abs(sec) < 1e6:
            sec *= 1e8
        bal = util.to_float(row.get("融资融券余额") or row.get("两融余额"))
        if bal is not None and abs(bal) < 1e6:
            bal *= 1e8
        if pg_market.upsert_margin_balance(
            day,
            market_scope="CN",
            financing_balance=fin,
            securities_balance=sec,
            margin_balance=bal,
            source_code=SOURCE,
        ):
            total += 1
    if total:
        pg_market.set_watermark(
            SOURCE, "margin_balance", "", watermark_day=date.today(), detail={"n": total}
        )
    print(f"akshare-ingest margin n={total}", flush=True)
    return total


def sync_north(ak: Any) -> int:
    """北向日度净流入：stock_hsgt_hist_em(symbol='北向资金')。"""
    df = util.call_ak(ak.stock_hsgt_hist_em, symbol="北向资金")
    if df is None:
        df = util.call_ak(
            getattr(ak, "stock_hsgt_north_net_flow_in_em", lambda **k: None)
        )
    rows = util.df_records(df)
    total = 0
    net_max = None
    for row in rows:
        day = util.day_s(row.get("日期") or row.get("date") or row.get("trade_date"))
        if not day:
            continue
        # 列名多变
        net = util.to_float(
            row.get("当日成交净买额")
            or row.get("净买额")
            or row.get("北向资金")
            or row.get("净流入")
            or row.get("value")
        )
        sh = util.to_float(row.get("买入额") or row.get("沪股通"))
        # 单位：常见万元
        def _wanyuan(v: float | None) -> float | None:
            if v is None:
                return None
            if abs(v) < 1e7:
                return v * 1e4
            return v

        net_y = _wanyuan(net)
        if net_y is None and sh is None:
            continue
        if pg_market.upsert_north_flow_daily(
            day,
            net_flow=net_y,
            buy_amount=_wanyuan(util.to_float(row.get("买入金额") or row.get("买入额"))),
            sell_amount=_wanyuan(util.to_float(row.get("卖出金额") or row.get("卖出额"))),
            sh_net=_wanyuan(util.to_float(row.get("沪股通"))),
            sz_net=_wanyuan(util.to_float(row.get("深股通"))),
            source_code=SOURCE,
        ):
            total += 1
            if net_max is None or day > net_max:
                net_max = day
    detail = {"n": total, "net_max": net_max}
    pg_market.set_watermark(
        SOURCE, "north_flow_daily", "", watermark_day=date.today(), detail=detail
    )
    print(f"akshare-ingest north n={total} net_max={net_max}", flush=True)
    return total


def sync_lhb(ak: Any) -> int:
    lookback = util.int_env("AKSHARE_INGEST_LHB_LOOKBACK", 7)
    detail_lim = util.int_env("AKSHARE_INGEST_LHB_DETAIL_LIMIT", 15)
    total = 0
    # stock_lhb_detail_em(start_date, end_date) — 非单日 date=
    end = date.today()
    start = end - timedelta(days=lookback - 1)
    ymd = lambda d: d.strftime("%Y%m%d")
    df = util.call_ak(
        ak.stock_lhb_detail_em, start_date=ymd(start), end_date=ymd(end)
    )
    for row in util.df_records(df):
        c = code6(str(row.get("代码") or row.get("股票代码") or row.get("code") or ""))
        if not c:
            continue
        day = util.day_s(
            row.get("上榜日") or row.get("日期") or row.get("交易日期") or end
        ) or end.isoformat()
        reason = str(row.get("上榜原因") or row.get("解读") or row.get("异动类型") or "")
        lid = pg_market.upsert_lhb_list(
            cn_equity_exchange(c),
            c,
            day,
            list_reason=reason,
            close=util.to_float(row.get("收盘价") or row.get("收盘")),
            change_pct=util.to_float(row.get("涨跌幅")),
            amount=util.to_float(row.get("成交额") or row.get("市场总成交额")),
            net_buy=util.to_float(row.get("龙虎榜净买额") or row.get("净买入")),
            name=str(row.get("名称") or row.get("股票简称") or ""),
            source_code=SOURCE,
        )
        if lid:
            total += 1
            det = util.call_ak(
                ak.stock_lhb_stock_detail_em,
                symbol=c,
                date=day.replace("-", ""),
                flag="买入",
            )
            for j, drow in enumerate(util.df_records(det)):
                if j >= detail_lim:
                    break
                pg_market.upsert_lhb_detail(
                    lid,
                    seat_name=str(
                        drow.get("交易营业部名称") or drow.get("营业部名称") or ""
                    ),
                    side="buy",
                    buy_amount=util.to_float(drow.get("买入金额") or drow.get("买入额")),
                    sell_amount=util.to_float(drow.get("卖出金额") or drow.get("卖出额")),
                    net_amount=util.to_float(drow.get("净额") or drow.get("买卖净额")),
                    source_code=SOURCE,
                )
            util.sleep_ms()
        if total >= util.int_env("AKSHARE_INGEST_LHB_LIST_LIMIT", 80):
            break
    if total:
        pg_market.set_watermark(
            SOURCE, "lhb_list", "", watermark_day=date.today(), detail={"n": total}
        )
    print(f"akshare-ingest lhb n={total}", flush=True)
    return total


def sync_hot(ak: Any) -> int:
    total = 0
    day = date.today().isoformat()
    df = util.call_ak(ak.stock_hot_rank_em)
    for i, row in enumerate(util.df_records(df)[:100]):
        c = code6(str(row.get("代码") or row.get("股票代码") or row.get("code") or ""))
        if not c:
            continue
        if pg_market.upsert_hot_rank_daily(
            day,
            "east",
            "hot_stock",
            i + 1,
            exchange_code=cn_equity_exchange(c),
            secu_code=c,
            name=str(row.get("股票名称") or row.get("名称") or ""),
            score=util.to_float(row.get("热度") or row.get("当前排名")),
            source_code=SOURCE,
        ):
            total += 1
    df2 = util.call_ak(getattr(ak, "stock_hot_rank_latest_em", lambda: None))
    for i, row in enumerate(util.df_records(df2)[:50]):
        c = code6(str(row.get("代码") or row.get("code") or ""))
        if not c:
            continue
        if pg_market.upsert_hot_rank_daily(
            day,
            "east",
            "hot_stock",
            i + 1,
            exchange_code=cn_equity_exchange(c),
            secu_code=c,
            name=str(row.get("名称") or ""),
            score=util.to_float(row.get("热度")),
            source_code=SOURCE,
        ):
            total += 1
    if total:
        pg_market.set_watermark(
            SOURCE, "hot_rank_daily", "", watermark_day=date.today(), detail={"n": total}
        )
    print(f"akshare-ingest hot n={total}", flush=True)
    return total


def run_p3(
    ak: Any,
    *,
    inc_sync: Callable[[str, str], None] | None = None,
) -> None:
    if util.env_flag("AKSHARE_INGEST_SKIP_P3", "0"):
        print("akshare-ingest p3 skip", flush=True)
        return

    def _inc(ds: str, st: str) -> None:
        if inc_sync:
            inc_sync(ds, st)

    for name, fn in (
        ("lifting", lambda: sync_lifting(ak)),
        ("margin_balance", lambda: sync_margin(ak)),
        ("north_flow_daily", lambda: sync_north(ak)),
        ("lhb_list", lambda: sync_lhb(ak)),
        ("hot_rank_daily", lambda: sync_hot(ak)),
    ):
        try:
            n = fn()
            _inc(name, "ok" if n else "empty")
        except Exception as exc:
            print(f"akshare-ingest p3 {name} failed: {exc}", flush=True)
            _inc(name, "fail")
    pg_market.set_watermark(SOURCE, "p3_round", "", watermark_day=date.today(), detail={})
    print("akshare-ingest p3_done", flush=True)
