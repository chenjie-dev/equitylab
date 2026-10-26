"""冷库 no-op：委托 packages/market-py（需已 pip install equitylab-market）。"""

from __future__ import annotations

from equitylab_market import pg as pg_market


def test_disabled_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    pg_market._conn = None
    pg_market._inner_cache.clear()
    assert pg_market.enabled() is False
    assert pg_market.ensure_security("SSE", "600519") is None


def test_ingest_empty_lists(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    pg_market._conn = None
    assert pg_market.ingest_sina_klines("SSE", "600519", daily=[], minute=[]) == {
        "daily": 0,
        "minute": 0,
    }
