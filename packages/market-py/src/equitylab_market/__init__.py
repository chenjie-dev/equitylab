"""EquityLab Postgres `market` 冷库客户端 + 采集侧 sina/符号工具。

写路径仅授权采集族（collector / history-ingest / 后续 adata job）。
- 边界：docs/market/2026-10-26-行情模块边界.md
- 基线表：docs/market/2026-10-26-market-postgres-schema.md
- adata 完整冷域：docs/market/2026-10-27-market-schema-adata完整域.md
"""

from __future__ import annotations

from equitylab_market import pg, pmc_calendar, sina, symbols

__all__ = ["pg", "pmc_calendar", "sina", "symbols"]
