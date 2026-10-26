"""兼容包名 `app.ashare` → 请改用 `app.cn_equity`。"""

from app.cn_equity.service import AshareService, CnEquityService

__all__ = ["AshareService", "CnEquityService"]
