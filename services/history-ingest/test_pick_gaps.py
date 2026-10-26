"""缺口排序纯逻辑（不连库）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "collector"))

# 避免 import main 时拉真实 equitylab_qdb / 连库
sys.modules.setdefault("equitylab_qdb", MagicMock())
sys.modules.setdefault("pg_market", MagicMock())

spec = importlib.util.spec_from_file_location("history_ingest_main", ROOT / "main.py")
assert spec and spec.loader
hi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hi)


def test_pick_gaps_orders_lowest_coverage_first():
    hi.pg_market.get_watermark = lambda *a, **k: None
    universe = [
        {"exchange": "SSE", "code": "600519", "name": "茅台"},
        {"exchange": "SZSE", "code": "000001", "name": "平安"},
        {"exchange": "SSE", "code": "601318", "name": "平安保险"},
    ]
    coverage = {
        ("SSE", "600519"): {"count": 120, "min_day": None, "max_day": None},
        ("SZSE", "000001"): {"count": 10, "min_day": None, "max_day": None},
        ("SSE", "601318"): {"count": 0, "min_day": None, "max_day": None},
    }
    gaps = hi.pick_gaps(universe, coverage, limit=10)
    assert [g["code"] for g in gaps] == ["601318", "000001"]
    assert gaps[0]["count"] == 0


def test_cn_equity_exchange_bse():
    assert hi.cn_equity_exchange("920088") == "BSE"
    assert hi.cn_equity_exchange("600519") == "SSE"
