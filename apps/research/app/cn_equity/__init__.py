"""中国 A 股产品读面（cn-equity）。

边界：历史 → Postgres `market`；盘中 → qdb；禁止回源上游。
非采集源名（sina/adata）。详见 docs/2026-10-26-行情模块边界.md。
"""

from .service import CnEquityService, AshareService

__all__ = ["CnEquityService", "AshareService"]
