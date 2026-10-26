"""A 股代码 ↔ 交易所标签（无 IO）。"""

from __future__ import annotations


def code6(raw: str) -> str | None:
    """仅接受有效 6 位数字代码。"""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) < 6:
        return None
    out = digits[-6:].zfill(6)
    return None if out == "000000" else out


def cn_equity_exchange(code: str) -> str:
    """6 位 A 股码 → SSE / SZSE / BSE。

    北交所：4/8 开头或 92xxxx；须先于「9→SSE」。
    """
    c = code6(code) or ""
    if c.startswith(("4", "8")) or c.startswith("92"):
        return "BSE"
    if c.startswith(("5", "6", "9")):
        return "SSE"
    return "SZSE"


# 旧名兼容（collector 曾用 ashare_exchange）
ashare_exchange = cn_equity_exchange
