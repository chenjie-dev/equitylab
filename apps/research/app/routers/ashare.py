"""兼容旧前缀 `/ashare` → 与 `/cn-equity` 同一端点集。新代码请用 cn-equity。"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.cn_equity import endpoints

router = APIRouter(prefix="/ashare", tags=["ashare-compat"])
router.include_router(endpoints)
