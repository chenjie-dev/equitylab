"""东方财富资金流（个股日度 + 概念板块快照）。

绕过 adata JSONP / 连接池偶发断连；对齐 get_capital_flow / all_capital_flow_east。
"""

from __future__ import annotations

from typing import Any

# 复用日线 secid 规则
try:
    from eastmoney_bars import secid as _secid
except Exception:  # pragma: no cover

    def _secid(exchange: str, code: str) -> str:
        c = (code or "").strip()
        if (exchange or "").upper() == "SSE" or c.startswith("6"):
            return f"1.{c}"
        return f"0.{c}"

_FLOW_COLUMNS = [
    "index_code",
    "index_name",
    "change_pct",
    "main_net_inflow",
    "main_net_inflow_rate",
    "max_net_inflow",
    "max_net_inflow_rate",
    "lg_net_inflow",
    "lg_net_inflow_rate",
    "mid_net_inflow",
    "mid_net_inflow_rate",
    "sm_net_inflow",
    "sm_net_inflow_rate",
    "stock_code",
    "stock_name",
]

_FID = {1: "f62", 5: "f164", 10: "f174"}
_FIELDS = {
    1: "f12,f14,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205",
    5: "f12,f14,f109,f164,f165,f166,f167,f168,f169,f170,f171,f172,f173,f257,f258",
    10: "f12,f14,f160,f174,f175,f176,f177,f178,f179,f180,f181,f182,f183,f260,f261",
}


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/zjlx/detail.html",
}


def _get_json(url: str, *, retries: int = 4) -> dict[str, Any]:
    import time

    last: Exception | None = None
    for i in range(max(1, retries)):
        try:
            import requests

            r = requests.get(url, headers=_HEADERS, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.8 * (i + 1))
    if last:
        raise last
    return {}


def _num(value: Any) -> float | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def stock_capital_flow_daily(
    exchange: str,
    stock_code: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """个股日度资金流（约近 120 日）；字段名对齐 adata。"""
    code = (stock_code or "").strip()
    if not code:
        return []
    sid = _secid(exchange, code)
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        "?lmt=0&klt=101&fields1=f1,f2,f3,f7"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&secid={sid}"
    )
    try:
        payload = _get_json(url)
    except Exception:
        return []
    data = payload.get("data") or {}
    lines = data.get("klines") or []
    out: list[dict[str, Any]] = []
    for line in lines:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        day = parts[0][:10]
        if start_date and day < start_date[:10]:
            continue
        if end_date and day > end_date[:10]:
            continue
        out.append(
            {
                "stock_code": code,
                "trade_date": day,
                "main_net_inflow": _num(parts[1]),
                "sm_net_inflow": _num(parts[2]),
                "mid_net_inflow": _num(parts[3]),
                "lg_net_inflow": _num(parts[4]),
                "max_net_inflow": _num(parts[5]),
            }
        )
    return out


def plate_capital_flow(
    days_type: int = 1,
    *,
    page_size: int = 50,
    max_pages: int = 40,
) -> list[dict[str, Any]]:
    """概念板块资金流快照；plate_code=index_code（BK****）。"""
    dt = days_type if days_type in _FID else 1
    fid = _FID[dt]
    fields = _FIELDS[dt]
    field_list = fields.split(",")
    out: list[dict[str, Any]] = []
    for pn in range(1, max(1, max_pages) + 1):
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            f"?fid={fid}&po=1&pz={page_size}&pn={pn}&np=1&fltt=2&invt=2"
            f"&fs=m:90+t:3&fields={fields}"
        )
        try:
            payload = _get_json(url)
        except Exception:
            break
        data = payload.get("data")
        if not data:
            break
        diff = data.get("diff") or []
        if not diff:
            break
        for item in diff:
            if not isinstance(item, dict):
                continue
            row: dict[str, Any] = {"days_type": dt}
            ok = True
            for i, col in enumerate(_FLOW_COLUMNS):
                if i >= len(field_list):
                    break
                raw = item.get(field_list[i])
                if raw == "-":
                    ok = False
                    break
                row[col] = raw
            if not ok:
                continue
            code = str(row.get("index_code") or "").strip()
            if not code:
                continue
            row["plate_code"] = code
            row["plate_name"] = str(row.get("index_name") or "")
            for k in (
                "main_net_inflow",
                "max_net_inflow",
                "lg_net_inflow",
                "mid_net_inflow",
                "sm_net_inflow",
                "change_pct",
            ):
                row[k] = _num(row.get(k))
            out.append(row)
        if len(diff) < page_size:
            break
    return out
