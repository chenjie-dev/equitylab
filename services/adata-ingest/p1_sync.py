"""adata-ingest P1：板块/成分/股本/申万/分红→adjust_factor。

边界同 main：只写 market；读路径零上游；vendor=ths|east 非产品名。
THS 概念成分走 get_concept_ths（按股）；东财目录/成分走 push2（绕过缺 CSV / MiniRacer）。
"""

from __future__ import annotations

import os
import time
from datetime import date
from typing import Any, Callable

from equitylab_market import pg as pg_market
from equitylab_market.symbols import code6, map_adata_exchange, map_index_exchange

import dividend_parse
import eastmoney_concepts
import eastmoney_dividend
import industry_sw as industry_sw_fetch

SOURCE = "adata"
SLEEP_MS = float(os.environ.get("ADATA_INGEST_SLEEP_MS", "300"))

# 种子指数成分（可覆盖）
_DEFAULT_INDEX_MEM = "000001,399001,399006,000300,000016,000852,000905"
# 无指数成分时的兜底个股
_DEFAULT_STOCKS = "600519,000001,000002,300750,601318"


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


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


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip() or default)
    except ValueError:
        return default


def _plate_kind(raw: str) -> str:
    s = (raw or "").strip()
    if s in ("行业", "industry"):
        return "industry"
    if s in ("地域", "地区", "region", "板块"):
        return "region"
    if s in ("概念", "concept"):
        return "concept"
    return "other" if s else "concept"


def _sw_level(industry_type: str, sw_code: str) -> int:
    t = (industry_type or "").strip()
    if "一级" in t:
        return 1
    if "二级" in t:
        return 2
    if "三级" in t:
        return 3
    c = "".join(ch for ch in sw_code if ch.isdigit()).zfill(6)
    if c.endswith("0000"):
        return 1
    if c.endswith("00"):
        return 2
    return 3


def _sw_parent(sw_code: str, level: int) -> str | None:
    """仅对纯数字申万码推父级；证监会等字母码不猜父级（避免 D45000→040000）。"""
    c = (sw_code or "").strip()
    if not c.isdigit() or level <= 1:
        return None
    c = c.zfill(6)
    if level == 2:
        return c[:2] + "0000"
    return c[:4] + "00"


def stock_universe(*, prefer_index_members: bool = True) -> list[dict[str, str]]:
    """P1 按股 API 的标的集：显式代码 ∪ 指数成分 ∪ security 存量。"""
    limit = _int_env("ADATA_INGEST_STOCK_LIMIT", 80)
    raw = os.environ.get("ADATA_INGEST_STOCK_CODES", "").strip()
    if not raw:
        raw = _DEFAULT_STOCKS
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(ex: str, code: str, name: str = "") -> None:
        c = code6(code)
        if not c:
            return
        exu = (ex or map_adata_exchange("", code=c)).upper()
        key = (exu, c)
        if key in seen:
            return
        seen.add(key)
        out.append({"exchange": exu, "code": c, "name": name or ""})

    for part in raw.split(","):
        _add(map_adata_exchange("", code=part.strip()), part.strip())

    if prefer_index_members:
        conn_ok = pg_market.enabled()
        if conn_ok:
            # 从已写入的 index 类 security 不够；直接读 index_member 关联太重，
            # 用 list stocks already in DB after index sync.
            for row in pg_market.list_securities(secu_category="stock", limit=limit * 3):
                _add(row["exchange"], row["code"], row.get("name") or "")
                if len(out) >= limit:
                    break

    return out[: max(1, limit)]


def sync_plate_ths(adata) -> int:
    n = 0
    try:
        df = adata.stock.info.all_concept_code_ths()
    except Exception as exc:
        print(f"adata-ingest p1 plate_ths failed: {exc}", flush=True)
        return 0
    for row in _df_records(df):
        code = str(row.get("concept_code") or row.get("index_code") or "").strip()
        if not code or code.lower() == "nan":
            continue
        name = str(row.get("name") or "")
        if pg_market.upsert_plate(
            "ths", code, name=name, plate_kind="concept", source_code=SOURCE
        ) is not None:
            n += 1
    print(f"adata-ingest p1 plate_ths n={n}", flush=True)
    pg_market.set_watermark(
        SOURCE, "plate", "ths", watermark_day=date.today(), detail={"n": n}
    )
    return n


def sync_plate_east() -> int:
    n = 0
    try:
        rows = eastmoney_concepts.all_concept_codes()
    except Exception as exc:
        print(f"adata-ingest p1 plate_east failed: {exc}", flush=True)
        return 0
    for row in rows:
        code = str(row.get("concept_code") or "").strip()
        if not code:
            continue
        if pg_market.upsert_plate(
            "east",
            code,
            name=str(row.get("name") or ""),
            plate_kind="concept",
            source_code=SOURCE,
        ) is not None:
            n += 1
    print(f"adata-ingest p1 plate_east n={n}", flush=True)
    pg_market.set_watermark(
        SOURCE, "plate", "east", watermark_day=date.today(), detail={"n": n}
    )
    return n


def sync_index_members(adata) -> int:
    raw = os.environ.get("ADATA_INGEST_INDEX_MEMBER_CODES", _DEFAULT_INDEX_MEM)
    codes = [code6(x.strip()) for x in raw.split(",") if x.strip()]
    codes = [c for c in codes if c]
    limit_idx = _int_env("ADATA_INGEST_INDEX_MEMBER_LIMIT", len(codes) or 6)
    total = 0
    for index_code in codes[: max(1, limit_idx)]:
        iex = map_index_exchange("", code=index_code)
        try:
            df = adata.stock.info.index_constituent(index_code=index_code)
        except Exception as exc:
            print(f"adata-ingest p1 index_member {index_code} failed: {exc}", flush=True)
            continue
        n = 0
        for row in _df_records(df):
            mc = code6(str(row.get("stock_code") or row.get("code") or ""))
            if not mc:
                continue
            mex = map_adata_exchange(str(row.get("exchange") or ""), code=mc)
            if pg_market.upsert_index_member(
                iex,
                index_code,
                mex,
                mc,
                member_name=str(row.get("short_name") or row.get("name") or ""),
                source_code=SOURCE,
            ):
                n += 1
        total += n
        print(f"adata-ingest p1 index_member {iex}:{index_code} n={n}", flush=True)
        pg_market.set_watermark(
            SOURCE,
            "index_member",
            f"{iex}:{index_code}",
            watermark_day=date.today(),
            detail={"n": n},
        )
        _sleep()
    return total


def sync_share_capital(adata, universe: list[dict[str, str]]) -> int:
    total = 0
    for item in universe:
        code = item["code"]
        try:
            df = adata.stock.info.get_stock_shares(stock_code=code, is_history=True)
        except Exception as exc:
            print(f"adata-ingest p1 shares {code} failed: {exc}", flush=True)
            continue
        n = 0
        for row in _df_records(df):
            day = row.get("change_date") or row.get("date")
            if not day:
                continue
            # list_a_shares ≈ A 股流通；float_shares 取同值（纯 A 场景）
            a_float = row.get("list_a_shares")
            if pg_market.upsert_share_capital(
                item["exchange"],
                code,
                str(day)[:10],
                total_shares=row.get("total_shares"),
                float_shares=a_float,
                float_shares_a=a_float,
                change_reason=str(row.get("change_reason") or ""),
                name=item.get("name") or "",
                source_code=SOURCE,
            ):
                n += 1
        total += n
        if n:
            pg_market.set_watermark(
                SOURCE,
                "share_capital",
                f"{item['exchange']}:{code}",
                watermark_day=date.today(),
                detail={"n": n},
            )
        print(f"adata-ingest p1 shares {code} n={n}", flush=True)
        _sleep()
    return total


def sync_industry_sw(adata, universe: list[dict[str, str]]) -> int:
    del adata  # 使用 industry_sw_fetch（容忍百度风控）；保留参数以对齐其它 sync_*
    total = 0
    for item in universe:
        code = item["code"]
        try:
            rows = industry_sw_fetch.get_industry_sw(code)
        except Exception as exc:
            print(f"adata-ingest p1 industry_sw {code} failed: {exc}", flush=True)
            continue
        # 先按 level 升序写码表，再写归属
        parsed: list[tuple[int, str, str, str | None]] = []
        for row in rows:
            sw = str(row.get("sw_code") or row.get("industry_code") or "").strip()
            if not sw or sw.lower() == "nan":
                continue
            itype = str(row.get("industry_type") or "")
            src = str(row.get("source") or "")
            is_em = sw.startswith("EM:") or "eastmoney" in src.lower()
            # 申万数字码 / 标明申万；东财 EM2016 回落；拒证监会门类等杂码
            if not is_em and "申万" not in itype and not sw.isdigit():
                continue
            level = _sw_level(itype, sw)
            name = str(row.get("industry_name") or row.get("name") or sw)
            parent = _sw_parent(sw, level)
            parsed.append((level, sw, name, parent))
        # 东财链：按出现顺序挂父级（同票一次返回的 1→2→3）
        by_level: dict[int, str] = {}
        fixed: list[tuple[int, str, str, str | None]] = []
        for level, sw, name, parent in sorted(parsed, key=lambda x: x[0]):
            if sw.startswith("EM:") and level > 1 and (level - 1) in by_level:
                parent = by_level[level - 1]
            by_level[level] = sw
            fixed.append((level, sw, name, parent))
        n = 0
        for level, sw, name, parent in fixed:
            if pg_market.upsert_industry_sw(
                sw, name, level, parent_code=parent, source_code=SOURCE
            ) and pg_market.upsert_security_industry(
                item["exchange"],
                code,
                sw,
                name=item.get("name") or "",
                source_code=SOURCE,
            ):
                n += 1
        total += n
        print(f"adata-ingest p1 industry_sw {code} n={n}", flush=True)
        _sleep()
    if total:
        pg_market.set_watermark(
            SOURCE, "industry_sw", "", watermark_day=date.today(), detail={"n": total}
        )
    return total


def sync_plate_members_by_stock(adata, universe: list[dict[str, str]]) -> int:
    """按股拉 THS/EAST 概念归属 → plate + plate_member（避开 THS MiniRacer 成分接口）。"""
    total = 0
    for item in universe:
        code = item["code"]
        for vendor, fetcher in (
            ("ths", lambda: adata.stock.info.get_concept_ths(stock_code=code)),
            ("east", lambda: adata.stock.info.get_concept_east(stock_code=code)),
        ):
            try:
                df = fetcher()
            except Exception as exc:
                print(
                    f"adata-ingest p1 plate_member {vendor} {code} failed: {exc}",
                    flush=True,
                )
                continue
            n = 0
            for row in _df_records(df):
                pcode = str(
                    row.get("concept_code") or row.get("plate_code") or ""
                ).strip()
                if not pcode or pcode.lower() == "nan":
                    continue
                pname = str(row.get("name") or row.get("plate_name") or "")
                pg_market.upsert_plate(
                    vendor,
                    pcode,
                    name=pname,
                    plate_kind="concept",
                    source_code=SOURCE,
                )
                if pg_market.upsert_plate_member(
                    vendor,
                    pcode,
                    item["exchange"],
                    code,
                    name=item.get("name") or "",
                    source_code=SOURCE,
                ):
                    n += 1
            total += n
            print(
                f"adata-ingest p1 plate_member {vendor} {code} n={n}",
                flush=True,
            )
        # 东财行业/地域板块
        try:
            df = adata.stock.info.get_plate_east(stock_code=code)
            n_pl = 0
            for row in _df_records(df):
                pcode = str(row.get("plate_code") or "").strip()
                if not pcode:
                    continue
                kind = _plate_kind(str(row.get("plate_type") or ""))
                pg_market.upsert_plate(
                    "east",
                    pcode,
                    name=str(row.get("plate_name") or ""),
                    plate_kind=kind,
                    source_code=SOURCE,
                )
                if pg_market.upsert_plate_member(
                    "east",
                    pcode,
                    item["exchange"],
                    code,
                    name=item.get("name") or "",
                    source_code=SOURCE,
                ):
                    n_pl += 1
            total += n_pl
            if n_pl:
                print(f"adata-ingest p1 plate_east_member {code} n={n_pl}", flush=True)
        except Exception as exc:
            print(f"adata-ingest p1 plate_east {code} failed: {exc}", flush=True)
        _sleep()
    if total:
        pg_market.set_watermark(
            SOURCE, "plate_member", "", watermark_day=date.today(), detail={"n": total}
        )
    return total


def sync_east_concept_constituents() -> int:
    """对种子东财概念拉全量成分（补充按股方向的遗漏）。"""
    raw = os.environ.get("ADATA_INGEST_EAST_CONCEPT_CODES", "BK0896,BK0475,BK1653")
    codes = [x.strip() for x in raw.split(",") if x.strip()]
    limit = _int_env("ADATA_INGEST_EAST_CONCEPT_LIMIT", len(codes) or 3)
    total = 0
    for pcode in codes[: max(1, limit)]:
        rows: list[dict[str, str]] = []
        for attempt in range(2):
            try:
                rows = eastmoney_concepts.concept_constituents(pcode)
            except Exception as exc:
                print(
                    f"adata-ingest p1 east_constituent {pcode} "
                    f"attempt={attempt} failed: {exc}",
                    flush=True,
                )
                rows = []
            if rows:
                break
            _sleep()
        pg_market.upsert_plate(
            "east", pcode, name="", plate_kind="concept", source_code=SOURCE
        )
        n = 0
        for row in rows:
            mc = code6(str(row.get("stock_code") or ""))
            if not mc:
                continue
            mex = map_adata_exchange("", code=mc)
            if pg_market.upsert_plate_member(
                "east",
                pcode,
                mex,
                mc,
                name=str(row.get("short_name") or ""),
                source_code=SOURCE,
            ):
                n += 1
        total += n
        print(
            f"adata-ingest p1 east_constituent {pcode} n={n} fetched={len(rows)}",
            flush=True,
        )
        pg_market.set_watermark(
            SOURCE,
            "plate_member",
            f"east:{pcode}",
            watermark_day=date.today(),
            detail={"n": n},
        )
        _sleep()
    return total


def sync_dividends(adata, universe: list[dict[str, str]]) -> dict[str, int]:
    """分红入库（东财 RPT_SHAREBONUS_DET）；有送转时写股数口径 adjust_factor。

    adata 百度 get_dividend 易重定向失败，仅作可选回落。
    """
    n_div = 0
    n_adj = 0
    n_fail = 0
    for item in universe:
        code = item["code"]
        rows: list[dict[str, Any]] = []
        try:
            rows = eastmoney_dividend.get_dividend(code)
        except Exception as exc:
            print(f"adata-ingest p1 dividend east {code} failed: {exc}", flush=True)
        if not rows:
            try:
                df = adata.stock.market.get_dividend(stock_code=code)
                for raw in _df_records(df):
                    plan = str(raw.get("dividend_plan") or "")
                    parsed = dividend_parse.parse_dividend_plan(plan)
                    rows.append(
                        {
                            "ex_date": raw.get("ex_dividend_date") or raw.get("ex_date"),
                            "announce_date": raw.get("report_date")
                            or raw.get("announce_date"),
                            "cash_per_share": parsed["cash_per_share"],
                            "stock_per_share": parsed["stock_per_share"],
                            "transfer_per_share": parsed["transfer_per_share"],
                            "dividend_plan": plan,
                        }
                    )
            except Exception as exc:
                n_fail += 1
                print(f"adata-ingest p1 dividend {code} failed: {exc}", flush=True)
                continue
        if not rows:
            n_fail += 1
            print(f"adata-ingest p1 dividend {code} empty", flush=True)
            _sleep()
            continue
        for row in rows:
            ex_raw = row.get("ex_date") or row.get("ex_dividend_date")
            if ex_raw is None or str(ex_raw).strip() in ("", "--", "nan", "None"):
                continue
            plan = str(row.get("dividend_plan") or row.get("remark") or "")
            cash = row.get("cash_per_share")
            stock = row.get("stock_per_share")
            transfer = row.get("transfer_per_share")
            if cash is None and stock is None and transfer is None and plan:
                parsed = dividend_parse.parse_dividend_plan(plan)
                cash, stock, transfer = (
                    parsed["cash_per_share"],
                    parsed["stock_per_share"],
                    parsed["transfer_per_share"],
                )
            ann = row.get("announce_date") or row.get("report_date")
            if pg_market.upsert_dividend(
                item["exchange"],
                code,
                str(ex_raw)[:10],
                announce_date=str(ann)[:10] if ann else None,
                record_date=row.get("record_date"),
                cash_per_share=cash,
                stock_per_share=stock,
                transfer_per_share=transfer,
                remark=plan[:512],
                name=item.get("name") or "",
                source_code=SOURCE,
            ):
                n_div += 1
            factors = dividend_parse.share_adjust_factors(stock, transfer)
            if factors and pg_market.upsert_adjust_factor(
                item["exchange"],
                code,
                str(ex_raw)[:10],
                forward_factor=factors[0],
                backward_factor=factors[1],
                source_code=SOURCE,
            ):
                n_adj += 1
        print(f"adata-ingest p1 dividend {code} rows={len(rows)}", flush=True)
        _sleep()
    if n_div:
        pg_market.set_watermark(
            SOURCE,
            "dividend",
            "",
            watermark_day=date.today(),
            detail={"dividend": n_div, "adjust_factor": n_adj, "fetch_fail": n_fail},
        )
    print(
        f"adata-ingest p1 dividend rows={n_div} adjust={n_adj} fetch_fail={n_fail}",
        flush=True,
    )
    return {"dividend": n_div, "adjust_factor": n_adj, "fetch_fail": n_fail}


def run_p1(adata, *, inc_sync: Callable[[str, str], None] | None = None) -> dict[str, Any]:
    """执行一整轮 P1；ADATA_INGEST_SKIP_P1=1 时跳过。"""
    if _env_flag("ADATA_INGEST_SKIP_P1", "0"):
        print("adata-ingest p1 skip=1", flush=True)
        return {"skipped": True}

    detail: dict[str, Any] = {}
    steps: list[tuple[str, Callable[[], Any]]] = [
        ("plate_ths", lambda: sync_plate_ths(adata)),
        ("plate_east", sync_plate_east),
        ("index_member", lambda: sync_index_members(adata)),
    ]
    for name, fn in steps:
        try:
            detail[name] = fn()
            if inc_sync:
                inc_sync(name, "ok")
        except Exception as exc:
            detail[name] = f"fail:{exc}"
            if inc_sync:
                inc_sync(name, "fail")
            print(f"adata-ingest p1 {name} failed: {exc}", flush=True)

    universe = stock_universe()
    detail["universe"] = len(universe)
    print(f"adata-ingest p1 universe n={len(universe)}", flush=True)

    for name, fn in (
        ("share_capital", lambda: sync_share_capital(adata, universe)),
        ("industry_sw", lambda: sync_industry_sw(adata, universe)),
        ("plate_member", lambda: sync_plate_members_by_stock(adata, universe)),
        ("east_constituent", sync_east_concept_constituents),
        ("dividend", lambda: sync_dividends(adata, universe)),
    ):
        try:
            detail[name] = fn()
            if inc_sync:
                inc_sync(name, "ok")
        except Exception as exc:
            detail[name] = f"fail:{exc}"
            if inc_sync:
                inc_sync(name, "fail")
            print(f"adata-ingest p1 {name} failed: {exc}", flush=True)

    pg_market.set_watermark(
        SOURCE, "p1_round", "", watermark_day=date.today(), detail=detail
    )
    print(f"adata-ingest p1_round_done {detail}", flush=True)
    return detail
