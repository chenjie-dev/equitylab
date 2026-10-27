"""东方财富概念目录 / 成分（绕过 adata 缺 CSV + MiniRacer）。

与 eastmoney_bars 同属采集族授权回源；产品面仍是 cn-equity / vendor=east。
"""

from __future__ import annotations

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


def all_concept_codes(*, page_size: int = 100, max_pages: int = 50) -> list[dict[str, str]]:
    """push2 clist fs=m:90+t:3 → [{concept_code,name}]。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for pn in range(1, max(1, max_pages) + 1):
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            f"?pn={pn}&pz={page_size}&po=1&np=1"
            "&fields=f12,f13,f14,f62&fid=f62&fs=m:90+t:3"
        )
        try:
            payload = _get_json(url)
        except Exception:
            break
        diff = ((payload.get("data") or {}).get("diff")) or []
        if not diff:
            break
        for row in diff:
            code = str(row.get("f12") or "").strip()
            name = str(row.get("f14") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            out.append({"concept_code": code, "name": name, "source": "eastmoney"})
        if len(diff) < page_size:
            break
    return out


def concept_constituents(concept_code: str, *, page_size: int = 200, max_pages: int = 50) -> list[dict[str, str]]:
    """BK**** 成分股。"""
    code = (concept_code or "").strip()
    if not code:
        return []
    out: list[dict[str, str]] = []
    for pn in range(1, max(1, max_pages) + 1):
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            f"?fid=f62&po=1&pz={page_size}&pn={pn}&np=1&fltt=2&invt=2"
            f"&fs=b:{code}&fields=f12,f14"
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
        for row in diff:
            sc = str(row.get("f12") or "").strip()
            if not sc:
                continue
            out.append({"stock_code": sc, "short_name": str(row.get("f14") or "")})
        if len(diff) < page_size:
            break
    return out
