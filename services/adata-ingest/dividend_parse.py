"""解析 adata/百度分红方案原文 → 每股现金/送股/转增。

仅覆盖常见「每10股…」表述；解析失败仍可把原文写入 dividend.remark。
送转推算的 adjust_factor 为股数口径（不含现金除权），须在文档标明。
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any


_NUM = r"(\d+(?:\.\d+)?)"


def parse_dividend_plan(plan: str) -> dict[str, Decimal | None]:
    """返回 cash_per_share / stock_per_share / transfer_per_share（每股）。"""
    text = (plan or "").strip().replace(" ", "").replace("\xa0", "")
    cash = stock = transfer = None
    if not text or "不分配" in text:
        return {"cash_per_share": None, "stock_per_share": None, "transfer_per_share": None}

    # 基数：每10股 / 10派…；缺省按 10
    base = Decimal(10)
    m_base = re.search(r"每?(\d+(?:\.\d+)?)股", text)
    if m_base:
        base = Decimal(m_base.group(1))
    if base <= 0:
        base = Decimal(10)

    m_cash = re.search(rf"派{_NUM}元", text)
    if m_cash:
        cash = Decimal(m_cash.group(1)) / base
    else:
        m_ps = re.search(rf"每股(?:派息|分红|现金红利)?{_NUM}元", text)
        if m_ps:
            cash = Decimal(m_ps.group(1))

    m_stock = re.search(rf"送{_NUM}", text)
    if m_stock:
        stock = Decimal(m_stock.group(1)) / base

    m_tr = re.search(rf"转(?:增)?{_NUM}", text)
    if m_tr:
        transfer = Decimal(m_tr.group(1)) / base

    return {
        "cash_per_share": cash,
        "stock_per_share": stock,
        "transfer_per_share": transfer,
    }


def share_adjust_factors(
    stock_per_share: Any = None,
    transfer_per_share: Any = None,
) -> tuple[Decimal, Decimal] | None:
    """股数口径：forward=1+送+转，backward=1/forward；无送转则 None。"""
    try:
        s = Decimal(str(stock_per_share or 0))
        t = Decimal(str(transfer_per_share or 0))
    except Exception:
        return None
    add = s + t
    if add <= 0:
        return None
    forward = Decimal(1) + add
    if forward <= 0:
        return None
    return forward, (Decimal(1) / forward)
