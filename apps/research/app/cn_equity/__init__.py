"""中国 A 股产品读面（cn-equity）。

边界：历史 → Postgres `market`；盘中 → qdb；禁止回源上游。
非采集源名（sina/adata）。详见 docs/market/2026-10-26-行情模块边界.md。

常用：`from app.cn_equity.service import CnEquityService, service`。
"""

__all__ = ["CnEquityService"]


def __getattr__(name: str):
    if name == "CnEquityService":
        from .service import CnEquityService as _Cls

        return _Cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
