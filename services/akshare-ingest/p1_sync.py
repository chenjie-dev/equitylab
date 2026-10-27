"""akshare-ingest P1：板块/成分/股本/行业/分红。"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from equitylab_market import pg as pg_market
from equitylab_market.symbols import code6, cn_equity_exchange, map_index_exchange

import industry_em2016
import util

SOURCE = util.SOURCE


def sync_concept_plates(ak: Any) -> int:
    limit = util.int_env("AKSHARE_INGEST_CONCEPT_LIMIT", 40)
    member_limit = util.int_env("AKSHARE_INGEST_CONCEPT_MEMBER_LIMIT", 30)
    seed = [
        x.strip()
        for x in os_env_list("AKSHARE_INGEST_CONCEPT_CODES")
    ]
    df = util.call_ak(ak.stock_board_concept_name_em)
    rows = util.df_records(df)
    if not rows:
        print("akshare-ingest concept plates empty", flush=True)
        return 0
    # 优先种子板名/代码
    picked: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("板块代码") or row.get("code") or "").strip()
        name = str(row.get("板块名称") or row.get("name") or "").strip()
        if seed and not any(s in (code, name) for s in seed):
            continue
        if code or name:
            picked.append({"code": code or name, "name": name or code})
        if len(picked) >= limit:
            break
    if not picked:
        for row in rows[:limit]:
            code = str(row.get("板块代码") or row.get("code") or "").strip()
            name = str(row.get("板块名称") or row.get("name") or "").strip()
            if code or name:
                picked.append({"code": code or name, "name": name or code})
    total = 0
    for item in picked:
        pcode = item["code"]
        pname = item["name"]
        if not pg_market.upsert_plate(
            "east", pcode, name=pname, plate_kind="concept", source_code=SOURCE
        ):
            continue
        cons = util.call_ak(ak.stock_board_concept_cons_em, symbol=pname)
        n_mem = 0
        for i, m in enumerate(util.df_records(cons)):
            if i >= member_limit:
                break
            c = code6(str(m.get("代码") or m.get("code") or ""))
            if not c:
                continue
            ex = cn_equity_exchange(c)
            name = str(m.get("名称") or m.get("name") or "")
            if pg_market.upsert_plate_member(
                "east", pcode, ex, c, name=name, source_code=SOURCE
            ):
                n_mem += 1
                total += 1
        print(f"akshare-ingest concept {pcode}/{pname} members={n_mem}", flush=True)
        util.sleep_ms()
    if total:
        pg_market.set_watermark(
            SOURCE, "plate_member", "", watermark_day=date.today(), detail={"n": total}
        )
    return total


def os_env_list(name: str) -> list[str]:
    import os

    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def sync_index_members(ak: Any) -> int:
    codes = os_env_list("AKSHARE_INGEST_INDEX_MEMBER_CODES") or [
        "000300",
        "000016",
        "399006",
    ]
    limit = util.int_env("AKSHARE_INGEST_INDEX_MEMBER_LIMIT", 3)
    total = 0
    for idx in codes[:limit]:
        c6 = code6(idx) or idx
        iex = map_index_exchange("", code=c6)
        pg_market.ensure_security(iex, c6, secu_category="index")
        df = util.call_ak(ak.index_stock_cons, symbol=c6)
        if df is None:
            df = util.call_ak(
                getattr(ak, "index_stock_cons_csindex", lambda **k: None), symbol=c6
            )
        n = 0
        for row in util.df_records(df):
            mc = code6(
                str(row.get("品种代码") or row.get("成分券代码") or row.get("code") or "")
            )
            if not mc:
                continue
            mex = cn_equity_exchange(mc)
            name = str(row.get("品种名称") or row.get("成分券名称") or row.get("name") or "")
            if pg_market.upsert_index_member(
                iex,
                c6,
                mex,
                mc,
                member_name=name,
                source_code=SOURCE,
            ):
                n += 1
                total += 1
        print(f"akshare-ingest index_member {c6} n={n}", flush=True)
        util.sleep_ms()
    if total:
        pg_market.set_watermark(
            SOURCE, "index_member", "", watermark_day=date.today(), detail={"n": total}
        )
    return total


def sync_share_capital(ak: Any, universe: list[dict[str, str]]) -> int:
    total = 0
    for item in universe:
        code = item["code"]
        df = util.call_ak(ak.stock_individual_info_em, symbol=code)
        rows = util.df_records(df)
        # 行多为 item/value
        kv = {
            str(r.get("item") or r.get("指标") or ""): r.get("value") or r.get("值")
            for r in rows
        }
        total_shares = util.to_shares(
            kv.get("总股本") or kv.get("总股本(股)")
        )
        float_a = util.to_shares(kv.get("流通股") or kv.get("流通A股"))
        if total_shares is None and float_a is None:
            util.sleep_ms()
            continue
        if pg_market.upsert_share_capital(
            item["exchange"],
            code,
            date.today(),
            total_shares=total_shares,
            float_shares=float_a,
            float_shares_a=float_a,
            change_reason="akshare_individual_info",
            name=item.get("name") or "",
            source_code=SOURCE,
        ):
            total += 1
        print(f"akshare-ingest share_capital {code} ok", flush=True)
        util.sleep_ms()
    if total:
        pg_market.set_watermark(
            SOURCE, "share_capital", "", watermark_day=date.today(), detail={"n": total}
        )
    return total


def sync_industry(ak: Any, universe: list[dict[str, str]]) -> int:
    """东财行业板成分 → industry_sw / security_industry（EM 伪码）。

    默认灌板成分（不限 P0 宇宙）；个股 info 行业链需显式
    AKSHARE_INGEST_INDUSTRY_PER_STOCK=1。
    """
    total = 0
    boards_n = 0
    cons_cap = util.int_env("AKSHARE_INGEST_INDUSTRY_CONS_LIMIT", 500)
    df = util.call_ak(ak.stock_board_industry_name_em)
    boards = util.df_records(df)[
        : util.int_env("AKSHARE_INGEST_INDUSTRY_BOARD_LIMIT", 80)
    ]
    for b in boards:
        name = str(b.get("板块名称") or b.get("name") or "").strip()
        if not name:
            continue
        icode = f"EM:1:{name[:24]}"
        pg_market.upsert_industry_sw(
            icode, name, 1, parent_code=None, source_code=SOURCE
        )
        boards_n += 1
        cons = util.call_ak(ak.stock_board_industry_cons_em, symbol=name)
        for row in util.df_records(cons)[:cons_cap]:
            c = code6(str(row.get("代码") or row.get("code") or ""))
            if not c:
                continue
            ex = cn_equity_exchange(c)
            if pg_market.upsert_security_industry(
                ex, c, icode, name=str(row.get("名称") or ""), source_code=SOURCE
            ):
                total += 1
        util.sleep_ms()
    # 可选：个股 info 行业链（默认关）
    if util.env_flag("AKSHARE_INGEST_INDUSTRY_PER_STOCK", "0"):
        for item in universe:
            df = util.call_ak(ak.stock_individual_info_em, symbol=item["code"])
            kv = {
                str(r.get("item") or r.get("指标") or ""): str(
                    r.get("value") or r.get("值") or ""
                )
                for r in util.df_records(df)
            }
            industry = (kv.get("行业") or "").strip()
            if not industry:
                continue
            parts = [
                p.strip()
                for p in industry.replace("/", "-").split("-")
                if p.strip()
            ]
            parent = None
            for i, iname in enumerate(parts[:3], start=1):
                icode = f"EM:{i}:{iname[:24]}"
                pg_market.upsert_industry_sw(
                    icode, iname, i, parent_code=parent, source_code=SOURCE
                )
                if pg_market.upsert_security_industry(
                    item["exchange"],
                    item["code"],
                    icode,
                    name=item.get("name") or "",
                    source_code=SOURCE,
                ):
                    total += 1
                parent = icode
            util.sleep_ms()

    # 行业板 push2 空时：东财 F10 EM2016 回落（沪深目录，不改 schema）
    em_n = 0
    if boards_n == 0 and util.env_flag("AKSHARE_INGEST_INDUSTRY_EM2016", "1"):
        em_lim = util.int_env("AKSHARE_INGEST_INDUSTRY_EM2016_LIMIT", 200)
        seed = list(universe)
        if len(seed) < em_lim:
            for row in pg_market.list_securities(
                secu_category="stock", limit=em_lim * 2
            ):
                if row["exchange"] not in ("SSE", "SZSE"):
                    continue
                seed.append(
                    {
                        "exchange": row["exchange"],
                        "code": row["code"],
                        "name": row.get("name") or "",
                    }
                )
                if len(seed) >= em_lim:
                    break
        seen: set[str] = set()
        for item in seed[:em_lim]:
            c = item["code"]
            if c in seen:
                continue
            seen.add(c)
            chain = industry_em2016.fetch_em2016(c)
            parent = None
            for node in chain:
                icode = str(node["sw_code"])
                pg_market.upsert_industry_sw(
                    icode,
                    str(node["industry_name"]),
                    int(node["level"]),
                    parent_code=parent,
                    source_code=SOURCE,
                )
                if pg_market.upsert_security_industry(
                    item["exchange"],
                    c,
                    icode,
                    name=item.get("name") or "",
                    source_code=SOURCE,
                ):
                    total += 1
                    em_n += 1
                parent = icode
            util.sleep_ms()
        print(f"akshare-ingest industry em2016 fallback n={em_n}", flush=True)

    detail = {
        "n": total,
        "boards": boards_n,
        "members": total,
        "em2016": em_n,
    }
    pg_market.set_watermark(
        SOURCE, "industry_sw", "", watermark_day=date.today(), detail=detail
    )
    print(
        f"akshare-ingest industry boards={boards_n} members={total} em2016={em_n}",
        flush=True,
    )
    return total


def sync_dividend(ak: Any, universe: list[dict[str, str]]) -> int:
    total = 0
    for item in universe[: util.int_env("AKSHARE_INGEST_DIVIDEND_LIMIT", 40)]:
        code = item["code"]
        df = util.call_ak(ak.stock_history_dividend_detail, symbol=code, indicator="分红")
        if df is None:
            df = util.call_ak(
                getattr(ak, "stock_fhps_detail_em", lambda **k: None), symbol=code
            )
        for row in util.df_records(df)[:20]:
            ex_date = util.day_s(
                row.get("除权除息日")
                or row.get("除权日")
                or row.get("股权登记日")
                or row.get("公告日期")
            )
            if not ex_date:
                continue
            cash = util.to_float(row.get("派息") or row.get("现金分红") or row.get("分红"))
            # 常见「10派X」口径：若数值较小按每股
            bonus = util.to_float(row.get("送股") or row.get("送股比例"))
            transfer = util.to_float(row.get("转增") or row.get("转增比例"))
            if pg_market.upsert_dividend(
                item["exchange"],
                code,
                ex_date=ex_date,
                announce_date=util.day_s(row.get("公告日期")),
                cash_per_share=cash,
                stock_per_share=bonus,
                transfer_per_share=transfer,
                name=item.get("name") or "",
                source_code=SOURCE,
            ):
                total += 1
        util.sleep_ms()
    if total:
        pg_market.set_watermark(
            SOURCE, "dividend", "", watermark_day=date.today(), detail={"n": total}
        )
    print(f"akshare-ingest dividend n={total}", flush=True)
    return total


def run_p1(
    ak: Any,
    universe: list[dict[str, str]],
    *,
    inc_sync: Callable[[str, str], None] | None = None,
) -> None:
    if util.env_flag("AKSHARE_INGEST_SKIP_P1", "0"):
        print("akshare-ingest p1 skip", flush=True)
        return

    def _inc(ds: str, st: str) -> None:
        if inc_sync:
            inc_sync(ds, st)

    for name, fn in (
        ("plate_member", lambda: sync_concept_plates(ak)),
        ("index_member", lambda: sync_index_members(ak)),
        ("share_capital", lambda: sync_share_capital(ak, universe)),
        ("industry_sw", lambda: sync_industry(ak, universe)),
        ("dividend", lambda: sync_dividend(ak, universe)),
    ):
        try:
            n = fn()
            _inc(name, "ok" if n else "empty")
        except Exception as exc:
            print(f"akshare-ingest p1 {name} failed: {exc}", flush=True)
            _inc(name, "fail")
    pg_market.set_watermark(
        SOURCE, "p1_round", "", watermark_day=date.today(), detail={"universe": len(universe)}
    )
    print("akshare-ingest p1_done", flush=True)
