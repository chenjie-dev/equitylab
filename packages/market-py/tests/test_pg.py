"""equitylab_market.pg：无 DATABASE_URL 时的 no-op。"""

from __future__ import annotations

from equitylab_market import pg


def test_disabled_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    pg._conn = None
    pg._inner_cache.clear()
    assert pg.enabled() is False
    assert pg.ensure_security("SSE", "600519") is None
    assert pg.upsert_bar_daily("SSE", "600519", "2024-01-02", {"close": 1}) is False
    assert pg.set_watermark("sina", "bar_daily", "SSE:600519") is False
    assert pg.is_trading_day("SSE", "2026-10-08") is None
    assert pg.load_trading_days("SSE", "2026-01-01", "2026-01-31") is None


def test_period_guard(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://invalid")
    pg._conn = None
    pg._warned = True
    from datetime import datetime, timezone

    assert (
        pg.upsert_bar_minute(
            "SSE",
            "600519",
            "30m",
            datetime.now(timezone.utc),
            "2024-01-02",
            {"close": 1},
        )
        is False
    )


def test_ingest_empty_lists(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    pg._conn = None
    assert pg.ingest_sina_klines("SSE", "600519", daily=[], minute=[]) == {
        "daily": 0,
        "minute": 0,
    }
