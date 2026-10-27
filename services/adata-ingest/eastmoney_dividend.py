"""东方财富分红明细（RPT_SHAREBONUS_DET）— 替代 adata 百度分红（易 30 次重定向）。

仍属采集族授权回源；写入 market.dividend 时 source_code=adata（厂商东财作管道）。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def _get_json(url: str) -> dict[str, Any]:
    try:
        from adata.common import requests as ar  # type: ignore

        return ar.request("get", url, headers={}, proxies={}).json()
    except Exception:
        import requests

        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.json()


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _day(value: Any) -> str | None:
    if value is None or value == "":
        return None
    s = str(value).strip()
    if s in ("--", "None", "nan"):
        return None
    return s[:10]


def get_dividend(stock_code: str, *, page_size: int = 50) -> list[dict[str, Any]]:
    """返回规范化行：ex_date / announce_date / cash|stock|transfer_per_share / plan。"""
    code = (stock_code or "").strip()
    if not code:
        return []
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get"
        "?sortColumns=EX_DIVIDEND_DATE&sortTypes=-1"
        f"&pageSize={max(1, min(page_size, 200))}&pageNumber=1"
        "&reportName=RPT_SHAREBONUS_DET&columns=ALL"
        f"&filter=(SECURITY_CODE%3D%22{code}%22)"
    )
    try:
        payload = _get_json(url)
    except Exception:
        return []
    if not payload.get("success"):
        return []
    rows = ((payload.get("result") or {}).get("data")) or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ex = _day(row.get("EX_DIVIDEND_DATE"))
        if not ex:
            # 预案未除权：跳过（ex_date 为 dividend 表必填）
            continue
        plan = str(row.get("IMPL_PLAN_PROFILE") or "")
        # 东财 PRETAX_BONUS_RMB / BONUS_RATIO / IT_RATIO 多为「每 10 股」口径
        pretax = _dec(row.get("PRETAX_BONUS_RMB"))
        bonus = _dec(row.get("BONUS_RATIO"))
        it = _dec(row.get("IT_RATIO"))
        cash = (pretax / Decimal(10)) if pretax is not None else None
        stock = (bonus / Decimal(10)) if bonus is not None else None
        transfer = (it / Decimal(10)) if it is not None else None
        out.append(
            {
                "stock_code": code,
                "ex_date": ex,
                "announce_date": _day(row.get("NOTICE_DATE") or row.get("PLAN_NOTICE_DATE")),
                "record_date": _day(row.get("EQUITY_RECORD_DATE")),
                "cash_per_share": cash,
                "stock_per_share": stock,
                "transfer_per_share": transfer,
                "dividend_plan": plan,
                "assign_progress": str(row.get("ASSIGN_PROGRESS") or ""),
            }
        )
    return out
