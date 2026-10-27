"""东方财富限售解禁（RPT_LIFT_STAGE）— 绕过 adata THS/MiniRacer。"""

from __future__ import annotations

from typing import Any

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/dxf/detail.html",
}


def _get_json(url: str) -> dict[str, Any]:
    import requests

    r = requests.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def stock_lifting(*, page_size: int = 50, max_pages: int = 20) -> list[dict[str, Any]]:
    """近端解禁列表；CURRENT_FREE_SHARES 单位为万股 → shares 换算为股。"""
    out: list[dict[str, Any]] = []
    for pn in range(1, max(1, max_pages) + 1):
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get"
            "?sortColumns=FREE_DATE&sortTypes=-1"
            f"&pageSize={page_size}&pageNumber={pn}"
            "&reportName=RPT_LIFT_STAGE&columns=ALL&source=WEB&client=WEB"
        )
        try:
            payload = _get_json(url)
        except Exception:
            break
        if not payload.get("success"):
            break
        rows = ((payload.get("result") or {}).get("data")) or []
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("SECURITY_CODE") or "").strip()
            day = str(row.get("FREE_DATE") or "")[:10]
            if not code or not day:
                continue
            # 万股 → 股
            wan = _num(row.get("ABLE_FREE_SHARES") or row.get("CURRENT_FREE_SHARES"))
            shares = wan * 10000.0 if wan is not None else None
            free_shares = _num(row.get("FREE_SHARES"))
            if shares is None and free_shares is not None:
                # FREE_SHARES 偶发已是股
                shares = free_shares if free_shares > 100000 else free_shares * 10000.0
            out.append(
                {
                    "stock_code": code,
                    "short_name": str(row.get("SECURITY_NAME_ABBR") or ""),
                    "lift_date": day,
                    "shares": shares,
                    "ratio": _num(row.get("TOTAL_RATIO") or row.get("FREE_RATIO")),
                    "holder_type": str(row.get("FREE_SHARES_TYPE") or "")[:128],
                    "remark": "",
                }
            )
        if len(rows) < page_size:
            break
    return out
