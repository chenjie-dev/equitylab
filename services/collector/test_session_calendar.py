"""session_calendar：无 DATABASE_URL 时回落工作日。"""

from __future__ import annotations

from datetime import date

import session_calendar as sc


def test_weekday_fallback_when_cache_empty(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with sc._lock:
        sc._trading_days = None
        sc._loaded_at = 0.0
        sc._window_start = None
        sc._window_end = None
    # 周五
    assert sc.is_cn_session_day(date(2026, 10, 9)) is True
    # 周六
    assert sc.is_cn_session_day(date(2026, 10, 10)) is False


def test_cached_set_overrides_weekday(monkeypatch):
    # 国庆：周四 10-01 在缓存外=非交易
    with sc._lock:
        sc._trading_days = {date(2026, 10, 8), date(2026, 10, 9)}
        sc._window_start = date(2026, 10, 1)
        sc._window_end = date(2026, 10, 15)
        sc._loaded_at = 1e18  # 永不过期
    monkeypatch.setattr(sc, "refresh", lambda force=False: True)
    assert sc.is_cn_session_day(date(2026, 10, 1)) is False
    assert sc.is_cn_session_day(date(2026, 10, 8)) is True
