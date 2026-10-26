"""cn_equity.pg_client：无 DATABASE_URL 时为空回落。"""

from __future__ import annotations

from app.cn_equity import pg_client


def test_bars_empty_without_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    pg_client._conn = None
    assert pg_client.enabled() is False
    assert pg_client.bars("600519", "1d", limit=10) == []
    assert pg_client.resolve_inner_code("600519") is None
