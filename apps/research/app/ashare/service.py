"""兼容：实现已迁至 app.cn_equity.service。"""

from app.cn_equity.service import *  # noqa: F403
from app.cn_equity.service import AshareService, CnEquityService, service

__all__ = ["AshareService", "CnEquityService", "service"]
