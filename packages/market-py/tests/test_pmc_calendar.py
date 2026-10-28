"""pmc_calendar：无 DB 时的解析/启发式；有包时抽检 2026。"""

from __future__ import annotations

from datetime import date

import pytest

from equitylab_market import pmc_calendar


def test_year_looks_unpublished_weekdays_only():
    # 构造「全年每个工作日都交易」→ 视为未公布节假日
    days: set[date] = set()
    d = date(2027, 1, 1)
    while d.year == 2027:
        if d.weekday() < 5:
            days.add(d)
        d = date.fromordinal(d.toordinal() + 1)
    assert pmc_calendar.year_looks_unpublished(days, 2027) is True
    assert pmc_calendar.year_looks_unpublished(set(), 2027) is True


def test_year_looks_published_when_holidays_removed():
    days: set[date] = set()
    d = date(2026, 1, 1)
    while d.year == 2026:
        if d.weekday() < 5:
            days.add(d)
        d = date.fromordinal(d.toordinal() + 1)
    days.discard(date(2026, 1, 1))
    days.discard(date(2026, 10, 1))
    assert pmc_calendar.year_looks_unpublished(days, 2026) is False


def test_pmc_2026_sse_if_installed():
    import sys

    # pmc 5.x 在 3.9 上 import 即 TypeError（非 ImportError），须先判版本
    if sys.version_info < (3, 10):
        pytest.skip("pandas_market_calendars 5.x 需 Python≥3.10（Compose 用 3.12）")
    pytest.importorskip("pandas_market_calendars")
    days = pmc_calendar.trading_days_for_year(2026, pmc_name="SSE")
    assert len(days) == 242
    assert date(2026, 1, 1) not in days
    assert date(2026, 10, 1) not in days
    assert date(2026, 10, 8) in days


def test_bse_maps_to_sse_not_bombay():
    assert pmc_calendar._PMC_NAME_BY_EXCHANGE["BSE"] == "SSE"
    assert pmc_calendar._PMC_NAME_BY_EXCHANGE["SZSE"] == "SSE"
