"""因子 IC：冷库日线确定性引擎（非伪随机、非截面 alphalens）。"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from app.factors.momentum_ic import compute_momentum_ic
from app.market_client import fetch_bars, last_bars_source, parse_cn_equity_universe
from app.models import FactorIcRequest

router = APIRouter(prefix="/factors", tags=["factors"])

# 约 242 个 A 股交易日/年；上限避免一次拉爆
_MAX_BARS = 2000
_MIN_BARS_FLOOR = 80


@router.post("/ic")
async def factor_ic(body: FactorIcRequest) -> dict[str, Any]:
    """单标的动量时序 Spearman IC；日线优先 market.bar_daily。"""
    name = (body.factor or "").strip().lower()
    if name != "momentum":
        raise HTTPException(
            status_code=400,
            detail="unsupported factor: only 'momentum' (single-name time-series IC)",
        )

    count = min(_MAX_BARS, max(_MIN_BARS_FLOOR, body.windowYears * 242 + body.lookback + body.horizon + 10))

    try:
        bars = await fetch_bars(
            body.universe,
            period="1d",
            count=count,
            adjust="none",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"bars fetch failed: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not bars:
        raise HTTPException(
            status_code=422,
            detail="empty bars: wait for collector/history-ingest; no demo fallback",
        )

    closes: list[float] = []
    for b in bars:
        try:
            closes.append(float(b["close"]))
        except (KeyError, TypeError, ValueError):
            continue

    src = last_bars_source()
    try:
        result = compute_momentum_ic(
            closes,
            lookback=body.lookback,
            horizon=body.horizon,
            min_obs=30,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    cn = parse_cn_equity_universe(body.universe)
    assumptions = [
        "single-name time-series Spearman IC (not cross-sectional / not alphalens)",
        f"factor = close[t]/close[t-{body.lookback}]-1 (past momentum)",
        f"label = close[t+{body.horizon}]/close[t]-1 (forward return; no peek into factor)",
        "prices: unadjusted closes as stored in bars path",
        "ICIR = mean/std of rolling Spearman windows when enough obs",
    ]
    if cn and src.startswith("postgres:"):
        assumptions.append("A-share daily bars from market.bar_daily (cold path)")
        demo = False
        mode = "cold_ts_ic"
    else:
        assumptions.append(
            "bars not from postgres cold path; treat metrics as exploratory"
        )
        demo = False
        mode = "ts_ic_fallback_bars"

    return {
        "factor": "momentum",
        "windowYears": body.windowYears,
        "universe": body.universe,
        "lookback": body.lookback,
        "horizon": body.horizon,
        "ic": result.ic,
        "icir": result.icir,
        "n_obs": result.n_obs,
        "bars": result.bars_used,
        "demo": demo,
        "mode": mode,
        "data_source": src,
        "source": src,
        "engine": "equitylab.factors.momentum_ic",
        "assumptions": assumptions,
        "rolling": {
            "window": result.rolling_window,
            "n_ics": result.rolling_ics,
        },
    }
