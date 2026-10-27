"""申万/行业归属：百度优先，东财 F10 EM2016 回落。

adata 百度接口风控时常返回 dict；东财 CompanySurvey.EM2016 为「一级-二级-三级」
文本链，写入 market.industry_sw（industry_code 前缀 EM:），不作产品路由名。
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs

COLUMNS = ["stock_code", "sw_code", "industry_name", "industry_type", "source"]

_F10_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        from adata.common import requests as ar  # type: ignore
        from adata.common.headers import baidu_headers  # type: ignore

        hdrs = headers or baidu_headers.json_headers
        return ar.request("get", url, headers=hdrs, proxies={}).json()
    except Exception:
        import requests

        r = requests.get(
            url,
            headers=headers or {},
            timeout=30,
            proxies={"http": None, "https": None},
        )
        r.raise_for_status()
        return r.json()


def _baidu_industry(stock_code: str) -> list[dict[str, Any]]:
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


def _ex_prefix(stock_code: str) -> str:
    c = "".join(ch for ch in stock_code if ch.isdigit())[-6:].zfill(6)
    if c.startswith(("5", "6", "9")):
        return f"SH{c}"
    return f"SZ{c}"


def _slug(name: str) -> str:
    # industry_code VARCHAR(32)；前缀「EM:n:」占 5 字符
    s = re.sub(r"\s+", "", (name or "").strip())
    return s[:24] if s else "UNK"


def _eastmoney_em2016(stock_code: str) -> list[dict[str, Any]]:
    """东财 F10「行业板块」文本链 → 伪申万码 EM:{level}:{name}。"""
    code = "".join(ch for ch in (stock_code or "") if ch.isdigit())[-6:]
    if not code:
        return []
    url = (
        "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
        f"?code={_ex_prefix(code)}"
    )
    try:
        payload = _get_json(
            url,
            headers={
                **_F10_HEADERS,
                "Referer": (
                    "https://emweb.securities.eastmoney.com/PC_HSF10/Index/Index"
                    f"?type=web&code={_ex_prefix(code)}"
                ),
            },
        )
    except Exception:
        return []
    rows = payload.get("jbzl") or []
    if not rows or not isinstance(rows, list):
        return []
    row = rows[0] if isinstance(rows[0], dict) else {}
    chain = str(row.get("EM2016") or "").strip()
    if not chain:
        return []
    parts = [p.strip() for p in chain.split("-") if p.strip()]
    if not parts:
        return []
    labels = ("一级行业", "二级行业", "三级行业")
    out: list[dict[str, Any]] = []
    for i, name in enumerate(parts[:3]):
        level = i + 1
        out.append(
            {
                "stock_code": code,
                "sw_code": f"EM:{level}:{_slug(name)}",
                "industry_name": name,
                "industry_type": labels[i] if i < len(labels) else f"{level}级行业",
                "source": "eastmoney_f10",
            }
        )
    return out


def get_industry_sw(stock_code: str) -> list[dict[str, Any]]:
    """单票行业；百度优先，空则东财 EM2016。风控或空 → []。"""
    rows = _baidu_industry(stock_code)
    if rows:
        return rows
    return _eastmoney_em2016(stock_code)
