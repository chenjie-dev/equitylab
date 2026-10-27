"""东方财富北向资金日度（RPT_MUTUAL_DEAL_HISTORY）。

001=深股通、003=沪股通（对齐 adata north_flow 注释）。
金额字段东财为「百万元」口径时 ×1e6 → 元；NET/BUY/SELL 近端常为 null 则跳过该日。
"""

from __future__ import annotations

from typing import Any

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/hsgt/index.html",
}


def _get_json(url: str) -> dict[str, Any]:
    import requests

    r = requests.get(url, headers=_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _amt_yuan(value: Any) -> float | None:
    """东财 NET/BUY/SELL 为百万元 → 元。"""
    if value is None or value == "":
        return None
    try:
        return float(value) * 1_000_000.0
    except (TypeError, ValueError):
        return None


def _fetch_type(mutual_type: str, *, pages: int = 3, page_size: int = 100) -> dict[str, dict[str, Any]]:
    by_day: dict[str, dict[str, Any]] = {}
    for pn in range(1, max(1, pages) + 1):
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get"
            "?sortColumns=TRADE_DATE&sortTypes=-1"
            f"&pageSize={page_size}&pageNumber={pn}"
            "&reportName=RPT_MUTUAL_DEAL_HISTORY&columns=ALL"
            "&source=WEB&client=WEB"
            f"&filter=(MUTUAL_TYPE%3D%22{mutual_type}%22)"
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
            day = str(row.get("TRADE_DATE") or "")[:10]
            if not day:
                continue
            net = _amt_yuan(row.get("NET_DEAL_AMT"))
            buy = _amt_yuan(row.get("BUY_AMT"))
            sell = _amt_yuan(row.get("SELL_AMT"))
            if net is None and buy is None and sell is None:
                continue
            by_day[day] = {"net": net, "buy": buy, "sell": sell}
        if len(rows) < page_size:
            break
    return by_day


def north_flow_daily(*, pages: int = 5) -> list[dict[str, Any]]:
    """合并沪/深港通 → [{trade_date, sh_net, sz_net, net_flow, buy_amount, sell_amount}]。"""
    # adata：003=沪、001=深
    hgt = _fetch_type("003", pages=pages)
    sgt = _fetch_type("001", pages=pages)
    days = sorted(set(hgt) | set(sgt), reverse=True)
    out: list[dict[str, Any]] = []
    for day in days:
        h = hgt.get(day) or {}
        s = sgt.get(day) or {}
        sh_net = h.get("net")
        sz_net = s.get("net")
        buy = None
        sell = None
        if h.get("buy") is not None or s.get("buy") is not None:
            buy = (h.get("buy") or 0.0) + (s.get("buy") or 0.0)
        if h.get("sell") is not None or s.get("sell") is not None:
            sell = (h.get("sell") or 0.0) + (s.get("sell") or 0.0)
        net = None
        if sh_net is not None or sz_net is not None:
            net = (sh_net or 0.0) + (sz_net or 0.0)
        if net is None and buy is None and sell is None:
            continue
        out.append(
            {
                "trade_date": day,
                "sh_net": sh_net,
                "sz_net": sz_net,
                "net_flow": net,
                "buy_amount": buy,
                "sell_amount": sell,
            }
        )
    return out
