"""符号映射。"""

from __future__ import annotations

from equitylab_market.sina import sina_symbol
from equitylab_market.symbols import cn_equity_exchange, code6


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
