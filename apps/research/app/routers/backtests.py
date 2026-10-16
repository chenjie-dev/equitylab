from typing import Any

from fastapi import APIRouter

from app.models import BacktestRequest

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post("/run")
def run_backtest(body: BacktestRequest) -> dict[str, Any]:
    """运行策略回测。MVP stub；不接真实券商。"""
    return {
        "strategy": body.strategy,
        "params": {"fast": body.fast, "slow": body.slow, "universe": body.universe},
        "metrics": {
            "cum_return": 0.128,
            "max_drawdown": -0.094,
            "trades": 42,
            "demo": True,
        },
        "assumptions": ["simplified demo backtest", "no live brokerage"],
    }
