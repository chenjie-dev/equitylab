"""dividend_parse 无 IO 单测（pytest 可在宿主机跑）。"""

from __future__ import annotations

from decimal import Decimal

import dividend_parse


def test_parse_10_pai():
    p = dividend_parse.parse_dividend_plan("10派12.447元(含税)")
    assert p["cash_per_share"] == Decimal("1.2447")
    assert p["stock_per_share"] is None


def test_parse_song_zhuan_pai():
    p = dividend_parse.parse_dividend_plan("每10股送1转2派3元")
    assert p["cash_per_share"] == Decimal("0.3")
    assert p["stock_per_share"] == Decimal("0.1")
    assert p["transfer_per_share"] == Decimal("0.2")


def test_share_adjust_factors():
    f = dividend_parse.share_adjust_factors(Decimal("0.1"), Decimal("0.2"))
    assert f is not None
    forward, backward = f
    assert forward == Decimal("1.3")
    assert abs(backward - Decimal("1") / Decimal("1.3")) < Decimal("1e-9")
    assert dividend_parse.share_adjust_factors(None, None) is None
