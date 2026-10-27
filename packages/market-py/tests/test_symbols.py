"""符号映射。"""

from __future__ import annotations

from equitylab_market.sina import sina_symbol
from equitylab_market.symbols import (
    cn_equity_exchange,
    code6,
    map_adata_exchange,
    map_index_exchange,
)


def test_cn_equity_exchange_bse_before_sse_nine():
    assert cn_equity_exchange("600519") == "SSE"
    assert cn_equity_exchange("000001") == "SZSE"
    assert cn_equity_exchange("830879") == "BSE"
    assert cn_equity_exchange("920088") == "BSE"
    assert cn_equity_exchange("900901") == "SSE"


def test_sina_symbol():
    assert sina_symbol("600519") == "sh600519"
    assert sina_symbol("830879") == "bj830879"
    assert code6("920088") == "920088"


def test_map_adata_exchange():
    assert map_adata_exchange("SH") == "SSE"
    assert map_adata_exchange("sz") == "SZSE"
    assert map_adata_exchange("BJ") == "BSE"
    assert map_adata_exchange("", code="600519") == "SSE"
    assert map_adata_exchange("未知", code="000001") == "SZSE"


def test_map_index_exchange():
    assert map_index_exchange("", code="000001") == "SSE"
    assert map_index_exchange("", code="000300") == "SSE"
    assert map_index_exchange("", code="399001") == "SZSE"
    assert map_index_exchange("", code="399006") == "SZSE"
    assert map_index_exchange("SH", code="000001") == "SSE"
    assert map_index_exchange("SZ", code="399001") == "SZSE"
    # 股票规则仍把 000001 当深市；指数映射不得回落成 SZSE
    assert cn_equity_exchange("000001") == "SZSE"
