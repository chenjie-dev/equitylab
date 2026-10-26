"""缺口排序纯逻辑。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

# 源码可编辑安装路径（未 pip install 时）
_SRC = Path(__file__).resolve().parents[1].parent / "packages" / "market-py" / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

sys.modules.setdefault("equitylab_qdb", MagicMock())

import main as hi  # noqa: E402
from equitylab_market.symbols import cn_equity_exchange  # noqa: E402


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
    assert cn_equity_exchange("920088") == "BSE"
    assert cn_equity_exchange("600519") == "SSE"
