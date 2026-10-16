from typing import Any

from fastapi import APIRouter

from app.models import FactorIcRequest

router = APIRouter(prefix="/factors", tags=["factors"])


@router.post("/ic")
def factor_ic(body: FactorIcRequest) -> dict[str, Any]:
    """计算因子 IC / ICIR。

    MVP：确定性伪指标；接入 alphalens 后替换。结果带 demo=True。
    """
    seed = sum(ord(c) for c in body.factor) + body.windowYears
    ic = ((seed % 37) - 18) / 100.0
    icir = ic / 0.08 if abs(ic) > 1e-6 else 0.0
    return {
        "factor": body.factor,
        "windowYears": body.windowYears,
        "ic": round(ic, 4),
        "icir": round(icir, 4),
        "demo": True,
        "engine": "pandas/numpy/alphalens (pending)",
    }
