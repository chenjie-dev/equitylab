from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from app.market_client import fetch_bars, last_bars_source, parse_cn_equity_universe
from app.models import BacktestRequest
from app.strategies.dual_ma import run_dual_ma

router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post("/run")
async def run_backtest(body: BacktestRequest) -> dict[str, Any]:
    """双均线回测：A 股日线优先 market 冷库；其它走 market-data /bars。不接真实券商。"""
    if body.strategy != "dual_ma":
        raise HTTPException(status_code=400, detail=f"unsupported strategy: {body.strategy}")
    if body.fast >= body.slow:
        raise HTTPException(status_code=400, detail="fast must be < slow")

    try:
        bars = await fetch_bars(
            body.universe,
            period=body.period,
            count=body.count,
            adjust=body.adjust,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"bars fetch failed: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not bars:
        raise HTTPException(status_code=422, detail="empty bars")

    try:
        result = run_dual_ma(bars, fast=body.fast, slow=body.slow)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    src = last_bars_source()
    cn = parse_cn_equity_universe(body.universe)
    assumptions = [
        "long-only dual MA crossover (golden/death cross)",
        "signal on close; same-day mark-to-market while in position",
        "no fees / slippage / borrow",
        "no live brokerage",
    ]
    if cn and src.startswith("postgres:"):
        assumptions.append("A-share daily bars from market.bar_daily (cn-equity cold path)")
    else:
        assumptions.append("bars from market-data /bars (non-A or cold empty fallback)")

    return {
        "strategy": body.strategy,
        "params": {
            "fast": body.fast,
            "slow": body.slow,
            "universe": body.universe,
            "period": body.period,
            "count": body.count,
            "adjust": body.adjust,
        },
        "metrics": {
            "cum_return": result.cum_return,
            "max_drawdown": result.max_drawdown,
            "trades": result.trades,
            "bars": result.bars_used,
        },
        "equity_curve": result.equity_curve,
        "mode": "market_bars",
        "data_source": src,
        "source": src,
        "assumptions": assumptions,
    }
