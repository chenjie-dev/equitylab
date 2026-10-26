"""pg_market 纯函数 / 无库时的 no-op 行为。"""

from __future__ import annotations

import os

import pg_market


def test_disabled_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    pg_market._conn = None
    pg_market._inner_cache.clear()
    assert pg_market.enabled() is False
    assert pg_market.ensure_security("SSE", "600519") is None
    assert pg_market.upsert_bar_daily("SSE", "600519", "2024-01-02", {"close": 1}) is False
    assert pg_market.set_watermark("sina", "bar_daily", "SSE:600519") is False


def test_period_guard(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://invalid")
    pg_market._conn = None
    pg_market._warned = True  # 静默
    from datetime import datetime, timezone

    assert (
        pg_market.upsert_bar_minute(
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
    pg_market._conn = None
    assert pg_market.ingest_sina_klines("SSE", "600519", daily=[], minute=[]) == {
        "daily": 0,
        "minute": 0,
    }
