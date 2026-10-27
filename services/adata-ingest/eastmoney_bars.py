"""东方财富日线（adata east 同源 HTTP）。

aarch64 Debian 上 py_mini_racer 仅有 muslc.so，adata 默认 THS/east facade
会落到 MiniRacer 并整段失败。P0 日线改直调 push2his，仍属 adata 采集族授权回源。
"""

from __future__ import annotations

import time
from typing import Any

# 与 adata.common.requests 同依赖栈；失败时退回标准 requests
def _post_json(url: str) -> dict[str, Any]:
    try:
        from adata.common import requests as ar  # type: ignore

        return ar.request("post", url, headers={}, proxies={}).json()
    except Exception:
        import requests

        r = requests.post(url, timeout=30)
        r.raise_for_status()
        return r.json()


def secid(exchange: str, code: str) -> str:
    """SSE→1. / SZSE·BSE→0.；北交所 93* 用 2.（对齐 adata east）。"""
    c = (code or "").strip()
    if c[:2] == "93":
        return f"2.{c}"
    ex = (exchange or "").upper()
    if ex == "SSE":
        return f"1.{c}"
    return f"0.{c}"


def daily_klines(
    exchange: str,
    code: str,
    *,
    start_date: str = "",
    retries: int = 6,
) -> list[dict[str, Any]]:
    """返回 trade_date/open/high/low/close/volume/amount 行。"""
    beg = "0"
    if start_date:
        beg = start_date.replace("-", "")[:8]
    sid = secid(exchange, code)
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={sid}&ut=fa5fd1943c7b386f172d6893dbfba10b"
        "&fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6"
        "&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61"
        f"&klt=101&fqt=1&beg={beg}&end=20500101&smplmt=100000&lmt=1000000"
    )
    last: Exception | None = None
    payload: dict[str, Any] = {}
    for i in range(max(1, retries)):
        try:
            payload = _post_json(url)
            break
        except Exception as exc:  # noqa: BLE001 — 上游偶发断连，重试
            last = exc
            time.sleep(1.0 * (i + 1))
    else:
        if last:
            raise last
        return []

    data = payload.get("data") or {}
    if str(data.get("code") or "") != str(code):
        return []
    rows: list[dict[str, Any]] = []
    for line in data.get("klines") or []:
        parts = str(line).split(",")
        if len(parts) < 7:
            continue
        day = parts[0][:10]
        if start_date and day < start_date[:10]:
            continue
        try:
            rows.append(
                {
                    "trade_date": day,
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                    "amount": float(parts[6]),
                    "change_pct": float(parts[8]) if len(parts) > 8 and parts[8] else None,
                    "change": float(parts[9]) if len(parts) > 9 and parts[9] else None,
                }
            )
        except (TypeError, ValueError):
            continue
    return rows
