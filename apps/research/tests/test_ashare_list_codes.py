"""Regression: ashare list_codes must never surface BINANCE/ONDO symbols."""

from __future__ import annotations

from app.ashare.qdb_client import ashare_exchange, qdb_symbol
from app.ashare.service import AshareService


def test_ashare_exchange_maps_bse_before_sse_nine():
    assert ashare_exchange("600519") == "SSE"
    assert ashare_exchange("000001") == "SZSE"
    assert ashare_exchange("510300") == "SSE"
    assert ashare_exchange("830879") == "BSE"
    assert ashare_exchange("835185") == "BSE"
    assert ashare_exchange("430047") == "BSE"
    # 92xxxx 是北交所新号段；不得因「9→SSE」误标沪市
    assert ashare_exchange("920088") == "BSE"
    assert ashare_exchange("900901") == "SSE"  # 沪 B
    assert qdb_symbol("830879") == "BSE:830879"
    assert qdb_symbol("920088") == "BSE:920088"


def test_list_codes_excludes_binance_and_ondo(monkeypatch):
    mixed = {
        "data": [
            {
                "stock_code": "BTCUSDT",
                "short_name": "BTCUSDT",
                "exchange": "BINANCE",
                "symbol": "BINANCE:BTCUSDT",
            },
            {
                "stock_code": "NVDA",
                "short_name": "NVDA",
                "exchange": "ONDO",
                "symbol": "ONDO:NVDA",
            },
            {
                "stock_code": "600519",
                "short_name": "贵州茅台",
                "exchange": "SSE",
                "symbol": "SSE:600519",
            },
            {
                "stock_code": "000001",
                "short_name": "平安银行",
                "exchange": "SZSE",
                "symbol": "SZSE:000001",
            },
            {
                "stock_code": "510300",
                "short_name": "沪深300ETF",
                "exchange": "SSE",
                "symbol": "SSE:510300",
            },
            {
                "stock_code": "830879",
                "short_name": "基康仪器",
                "exchange": "BSE",
                "symbol": "BSE:830879",
            },
            {
                "stock_code": "920088",
                "short_name": "北交示例",
                "exchange": "BSE",
                "symbol": "BSE:920088",
            },
        ],
        "source": "qdb",
    }
    monkeypatch.setattr(
        "app.ashare.qdb_client.snapshots_all",
        lambda: mixed,
    )

    svc = AshareService()
    out = svc.list_codes(limit=8000)
    codes = {r["stock_code"]: r for r in out["data"]}

    assert "BTCUSDT" not in codes
    assert "00NVDA" not in codes
    assert "NVDA" not in codes
    assert "600519" in codes
    assert "000001" in codes
    assert "510300" in codes
    assert "830879" in codes
    assert "920088" in codes
    assert codes["830879"]["exchange"] == "BJ"
    assert codes["830879"]["symbol"] == "830879.BJ"
    assert codes["920088"]["exchange"] == "BJ"
    for r in out["data"]:
        assert r["stock_code"].isdigit() and len(r["stock_code"]) == 6
        assert r["exchange"] in ("SH", "SZ", "BJ")
        assert not str(r["stock_code"]).endswith("USDT")
