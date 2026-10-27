"""申万行业：对齐 adata get_industry_sw，但容忍百度风控 dict。

adata 在 Result={'code':403,...} 时会对 int 做 for 循环崩溃；本模块返回空表而非抛错。
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

COLUMNS = ["stock_code", "sw_code", "industry_name", "industry_type", "source"]


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        from adata.common import requests as ar  # type: ignore
        from adata.common.headers import baidu_headers  # type: ignore

        hdrs = headers or baidu_headers.json_headers
        return ar.request("get", url, headers=hdrs, proxies={}).json()
    except Exception:
        import requests

        r = requests.get(url, headers=headers or {}, timeout=30)
        r.raise_for_status()
        return r.json()


def get_industry_sw(stock_code: str) -> list[dict[str, Any]]:
    """单票申万一/二级；风控或空 → []。"""
    code = (stock_code or "").strip()
    if not code:
        return []
    code_list = [{"code": code, "market": "ab", "type": "stock"}]
    url = (
        "https://finance.pae.baidu.com/api/getrelatedblock"
        f"?stock={json.dumps(code_list, ensure_ascii=False)}&finClientType=pc"
    )
    try:
        res_json = _get_json(url)
    except Exception:
        return []
    result = res_json.get("Result")
    if not result or not isinstance(result, dict):
        return []
    # 风控：{"code":403,"msg":"hit risk",...}
    if "code" in result and "list" not in result and code not in result:
        return []
    out: list[dict[str, Any]] = []
    for key, value in result.items():
        if not isinstance(value, list):
            continue
        for concept_type in value:
            if not isinstance(concept_type, dict):
                continue
            if concept_type.get("name") != "行业":
                continue
            for item in concept_type.get("list") or []:
                if not isinstance(item, dict):
                    continue
                sw = ""
                try:
                    q = parse_qs(str(item.get("xcx_query") or ""))
                    sw = (q.get("code") or [""])[0]
                except Exception:
                    sw = ""
                out.append(
                    {
                        "stock_code": key,
                        "sw_code": sw,
                        "industry_name": str(item.get("name") or ""),
                        "industry_type": str(item.get("describe") or ""),
                        "source": "百度股市通",
                    }
                )
    return out
