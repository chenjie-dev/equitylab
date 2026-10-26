"""EquityLab Postgres `market` 冷库客户端 + 采集侧 sina/符号工具。

写路径仅授权采集族（collector / history-ingest）。
详见 docs/market/2026-10-26-行情模块边界.md。
"""

from __future__ import annotations

from equitylab_market import pg, sina, symbols

__all__ = ["pg", "sina", "symbols"]
