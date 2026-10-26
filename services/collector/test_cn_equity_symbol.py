"""北交所符号：新浪 bj 前缀 ↔ qdb BSE:6 位码。"""

from __future__ import annotations

from main import cn_equity_exchange, parse_sina, sina_symbol, split_symbol


def test_cn_equity_exchange_bse_before_sse_nine() -> None:
    assert cn_equity_exchange("600519") == "SSE"
    assert cn_equity_exchange("000001") == "SZSE"
    assert cn_equity_exchange("830879") == "BSE"
    assert cn_equity_exchange("430047") == "BSE"
    assert cn_equity_exchange("920088") == "BSE"
    assert cn_equity_exchange("900901") == "SSE"


def test_sina_and_split_symbol() -> None:
    assert sina_symbol("600519") == "sh600519"
    assert sina_symbol("000001") == "sz000001"
    assert sina_symbol("830879") == "bj830879"
    assert sina_symbol("920088") == "bj920088"
    assert split_symbol("830879") == ("BSE", "830879")
    assert split_symbol("920088") == ("BSE", "920088")


def test_parse_sina_bj() -> None:
    body = (
        'var hq_str_bj830879="基康仪器,10.00,9.90,10.10,10.20,9.80,'
        '10.09,10.11,1000,10000,'
        "100,10.09,200,10.08,0,0,0,0,0,0,"
        '50,10.11,0,0,0,0,0,0,0,0,2024-01-02,15:00:00,00";\n'
    )
    rows = parse_sina(body)
    assert len(rows) == 1
    assert rows[0]["exchange"] == "BSE"
    assert rows[0]["code"] == "830879"
    assert rows[0]["name"] == "基康仪器"
    assert rows[0]["price"] == 10.10
