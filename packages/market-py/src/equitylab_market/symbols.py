"""A 股代码 ↔ 交易所标签（无 IO）。"""

from __future__ import annotations


def code6(raw: str) -> str | None:
    """仅接受有效 6 位数字代码。"""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) < 6:
        return None
    out = digits[-6:].zfill(6)
    return None if out == "000000" else out


def is_cn_listed_equity(code: str) -> bool:
    """是否可作为 A 股现货（含 ETF/B 股）进 cn-equity 宇宙 / 冷日线补数。

    排除误混入的指数段：980*（见 map_index_exchange）、399/395 深证指数。
    北交所 4/8/92、沪 5/6/9（含 900 B 股）、深主板/创业板照常接受。
    """
    c = code6(code) or ""
    if not c:
        return False
    if c.startswith(("980", "399", "395")):
        return False
    return True


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


def map_adata_exchange(raw: str, *, code: str = "") -> str:
    """adata 交易所字段（SH/SZ/BJ 或中文）→ SSE/SZSE/BSE。

    无法识别时回落 cn_equity_exchange(code)。
    """
    s = (raw or "").strip().upper()
    if s in ("SSE", "SZSE", "BSE"):
        return s
    if s in ("SH", "SHA", "XSHG", "上海", "沪"):
        return "SSE"
    if s in ("SZ", "SZA", "XSHE", "深圳", "深"):
        return "SZSE"
    if s in ("BJ", "BSE", "XBEI", "北京", "北"):
        return "BSE"
    if code:
        return cn_equity_exchange(code)
    return "SZSE"


def map_index_exchange(raw: str = "", *, code: str = "") -> str:
    """指数代码 → 交易所（勿用股票前缀：000001 是上证指数，不是深市个股）。

    优先 adata 交易所字段；否则 399/395→SZSE，000/880→SSE，4/8/92→BSE。
    """
    s = (raw or "").strip().upper()
    if s in ("SSE", "SZSE", "BSE"):
        return s
    if s in ("SH", "SHA", "XSHG", "上海", "沪"):
        return "SSE"
    if s in ("SZ", "SZA", "XSHE", "深圳", "深"):
        return "SZSE"
    if s in ("BJ", "XBEI", "北京", "北"):
        return "BSE"
    c = code6(code) or (code or "").strip()
    if c.startswith(("399", "395", "980")):
        return "SZSE"
    if c.startswith(("4", "8")) or c.startswith("92"):
        return "BSE"
    if c.startswith(("000", "880", "999")):
        return "SSE"
    if code:
        return cn_equity_exchange(code)
    return "SSE"
