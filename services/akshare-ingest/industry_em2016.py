"""东财 F10 EM2016 行业链（与 adata-ingest 同源 HTTP；不改 schema）。

行业板 push2 不可达时，由 akshare-ingest sync_industry 回落调用。
"""

from __future__ import annotations

import re
from typing import Any

import requests

_F10_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _ex_prefix(stock_code: str) -> str:
    c = "".join(ch for ch in (stock_code or "") if ch.isdigit())[-6:].zfill(6)
    if c.startswith(("5", "6", "9")):
        return f"SH{c}"
    return f"SZ{c}"


def _slug(name: str) -> str:
    s = re.sub(r"\s+", "", (name or "").strip())
    return s[:24] if s else "UNK"


def fetch_em2016(stock_code: str) -> list[dict[str, Any]]:
    """返回 [{sw_code, industry_name, level}, ...]。"""
    code = "".join(ch for ch in (stock_code or "") if ch.isdigit())[-6:]
    if not code:
        return []
    pref = _ex_prefix(code)
    url = (
        "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
        f"?code={pref}"
    )
    try:
        r = requests.get(
            url,
            headers={
                **_F10_HEADERS,
                "Referer": (
                    "https://emweb.securities.eastmoney.com/PC_HSF10/Index/Index"
                    f"?type=web&code={pref}"
                ),
            },
            timeout=30,
            proxies={"http": None, "https": None},
        )
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return []
    rows = payload.get("jbzl") or []
    if not rows or not isinstance(rows, list):
        return []
    row = rows[0] if isinstance(rows[0], dict) else {}
    chain = str(row.get("EM2016") or "").strip()
    if not chain:
        return []
    parts = [p.strip() for p in chain.split("-") if p.strip()]
    out: list[dict[str, Any]] = []
    for i, name in enumerate(parts[:3]):
        level = i + 1
        out.append(
            {
                "sw_code": f"EM:{level}:{_slug(name)}",
                "industry_name": name,
                "level": level,
            }
        )
    return out
