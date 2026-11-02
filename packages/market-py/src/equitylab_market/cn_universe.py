"""A 股全市场代码表：新浪 Market_Center → qdb docs `cn-equity:codes`。

授权采集族（history-ingest / collector）回源写 docs；读路径只读该 docs。
`hs_a` 含沪/深/北（bj*）；ETF 等不在 hs_a 的标的由 seed 合并补入。
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import requests

from equitylab_market.symbols import cn_equity_exchange, code6

# 与 collector 默认种子对齐（含 ETF / 北交所热门）
DEFAULT_SEED = (
    "600519,000001,300750,601318,000858,002594,600036,601012,688981,510300,"
    "830879,835185,000568,600900,601899,300059,002475,600276,000333,601166,"
    "600030,002415"
)

CODES_DOC_KEY = "cn-equity:codes"
_SINA_LIST = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeData"
)
_SINA_COUNT = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "Market_Center.getHQNodeStockCount"
)
_PAGE_SIZE = 100
SINA_HQ_BATCH_MAX = 100

_UA = {
    "User-Agent": "equitylab-market",
    "Referer": "https://finance.sina.com.cn",
}


def seed_codes_from_env() -> list[str]:
    raw = (
        os.environ.get("COLLECTOR_CODES")
        or os.environ.get("QDB_FEED_CODES")
        or os.environ.get("CN_EQUITY_SEED_CODES")
        or DEFAULT_SEED
    )
    return _normalize_code_list(raw)


def universe_mode() -> str:
    """full = 新浪 hs_a + seed；seed = 仅 seed 列表。"""
    mode = (os.environ.get("CN_EQUITY_UNIVERSE") or "full").strip().lower()
    return "seed" if mode in ("seed", "hot", "priority") else "full"


def quote_batch_size() -> int:
    n = int(os.environ.get("CN_EQUITY_QUOTE_BATCH", "100"))
    return max(1, min(SINA_HQ_BATCH_MAX, n))


def universe_refresh_sec() -> float:
    return max(300.0, float(os.environ.get("CN_EQUITY_UNIVERSE_REFRESH_SEC", "21600")))


def kline_backfill_codes(seed: list[str], universe: list[str]) -> list[str]:
    raw = (os.environ.get("CN_EQUITY_KLINE_CODES") or "").strip().lower()
    if raw in ("all", "*"):
        return list(universe)
    if raw in ("none", "off", "0"):
        return []
    if raw:
        return _normalize_code_list(raw)
    if universe_mode() == "seed":
        return list(universe)
    return list(seed)


def _normalize_code_list(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        parts = raw
    else:
        parts = re.split(r"[,;\s]+", str(raw))
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        c = code6(str(p))
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def sina_symbol(code: str) -> str:
    c = code6(code) or "000000"
    prefix = {"SSE": "sh", "SZSE": "sz", "BSE": "bj"}[cn_equity_exchange(c)]
    return prefix + c


def _parse_sina_json(text: str) -> Any:
    text = (text or "").strip()
    if not text or text == "null":
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        fixed = re.sub(r"([{,])([A-Za-z_][A-Za-z0-9_]*)(:)", r'\1"\2"\3', text)
        return json.loads(fixed)


def fetch_hs_a_count(session: requests.Session | None = None) -> int | None:
    sess = session or requests.Session()
    r = sess.get(_SINA_COUNT, params={"node": "hs_a"}, headers=_UA, timeout=20)
    r.raise_for_status()
    data = _parse_sina_json(r.content.decode("utf-8", "replace"))
    if isinstance(data, (int, float)):
        return int(data)
    if isinstance(data, str) and data.isdigit():
        return int(data)
    return None


def fetch_hs_a_universe(
    session: requests.Session | None = None,
    *,
    page_delay_s: float = 0.05,
) -> list[dict[str, Any]]:
    """拉取新浪 `hs_a` 全表（含北交所 bj*）。返回 [{code,name,exchange,sina}, ...]。"""
    sess = session or requests.Session()
    total = fetch_hs_a_count(sess)
    pages_hint = ((total or 6000) + _PAGE_SIZE - 1) // _PAGE_SIZE
    by_code: dict[str, dict[str, Any]] = {}
    empty_streak = 0
    for page in range(1, pages_hint + 5):
        r = sess.get(
            _SINA_LIST,
            params={
                "page": page,
                "num": _PAGE_SIZE,
                "sort": "symbol",
                "asc": 1,
                "node": "hs_a",
                "symbol": "",
                "_s_r_a": "init",
            },
            headers=_UA,
            timeout=30,
        )
        r.raise_for_status()
        rows = _parse_sina_json(r.content.decode("utf-8", "replace"))
        if not isinstance(rows, list) or not rows:
            empty_streak += 1
            if empty_streak >= 2:
                break
            continue
        empty_streak = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = code6(str(row.get("code") or "")) or "000000"
            if code == "000000":
                continue
            if code.startswith(("980", "399", "395")):
                continue
            sym = str(row.get("symbol") or "")
            if sym.startswith("bj"):
                exchange = "BSE"
            elif sym.startswith("sh"):
                exchange = "SSE"
            elif sym.startswith("sz"):
                exchange = "SZSE"
            else:
                exchange = cn_equity_exchange(code)
            by_code[code] = {
                "code": code,
                "name": str(row.get("name") or ""),
                "exchange": exchange,
                "sina": sym or sina_symbol(code),
            }
        if len(rows) < _PAGE_SIZE:
            break
        if page_delay_s > 0:
            time.sleep(page_delay_s)
    return list(by_code.values())


def merge_seed_rows(
    universe: list[dict[str, Any]],
    seed: list[str],
    *,
    names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    by = {r["code"]: dict(r) for r in universe}
    names = names or {}
    for code in seed:
        if code in by:
            continue
        by[code] = {
            "code": code,
            "name": names.get(code, ""),
            "exchange": cn_equity_exchange(code),
            "sina": sina_symbol(code),
        }
    seed_set = set(seed)
    head = [by[c] for c in seed if c in by]
    tail = sorted(
        (r for c, r in by.items() if c not in seed_set),
        key=lambda r: r["code"],
    )
    return head + tail


def build_codes_doc(
    rows: list[dict[str, Any]],
    *,
    mode: str,
    kline_codes: list[str],
    source: str,
) -> dict[str, Any]:
    return {
        "updated_at_ns": int(time.time() * 1_000_000_000),
        "source": source,
        "universe": mode,
        "count": len(rows),
        "kline_codes": list(kline_codes),
        "quote_batch": quote_batch_size(),
        "note": (
            "A-share history-only: catalog for cold bars; "
            "live quotes/depth disabled by default (COLLECTOR_SKIP_CN_EQUITY=1)"
        ),
        "codes": [
            {
                "code": r["code"],
                "name": r.get("name") or "",
                "exchange": r["exchange"],
            }
            for r in rows
        ],
    }


def codes_doc_items(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": CODES_DOC_KEY, "value": doc}]


def resolve_universe(
    *,
    session: requests.Session | None = None,
    seed: list[str] | None = None,
    seed_names: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """按 CN_EQUITY_UNIVERSE 解析代码表，并构造待写入的 docs value。"""
    seed = list(seed or seed_codes_from_env())
    mode = universe_mode()
    source = "seed"
    rows: list[dict[str, Any]]
    if mode == "full":
        try:
            fetched = fetch_hs_a_universe(session)
            if len(fetched) < 100:
                raise RuntimeError(f"hs_a too small: {len(fetched)}")
            rows = merge_seed_rows(fetched, seed, names=seed_names)
            source = "sina:hs_a+seed"
        except Exception as exc:
            print(f"cn_equity universe fetch failed, fallback seed: {exc}", flush=True)
            rows = merge_seed_rows([], seed, names=seed_names)
            source = f"seed(fallback:{exc.__class__.__name__})"
            mode = "seed"
    else:
        rows = merge_seed_rows([], seed, names=seed_names)
    codes = [r["code"] for r in rows]
    kline = kline_backfill_codes(seed, codes)
    doc = build_codes_doc(rows, mode=mode, kline_codes=kline, source=source)
    return rows, doc
