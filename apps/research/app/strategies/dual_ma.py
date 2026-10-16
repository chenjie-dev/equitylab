"""双均线金叉死叉：短均线上穿长均线买入，下穿卖出；全仓多头 / 空仓。

用收盘价做 SMA；信号在当日收盘确认，次日开盘才可成交——MVP 简化为
「信号日收盘换仓」，用当日收益仍算持仓（偏乐观，须在 assumptions 标明）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class DualMaResult:
    equity_curve: list[dict[str, Any]]
    cum_return: float
    max_drawdown: float
    trades: int
    bars_used: int


def _sma(values: Sequence[float], end: int, window: int) -> float | None:
    if end + 1 < window:
        return None
    start = end + 1 - window
    return sum(values[start : end + 1]) / window


def run_dual_ma(
    bars: Sequence[dict[str, Any]],
    *,
    fast: int,
    slow: int,
) -> DualMaResult:
    if fast < 1 or slow < 1:
        raise ValueError("fast/slow must be >= 1")
    if fast >= slow:
        raise ValueError("fast must be < slow")
    if len(bars) < slow + 1:
        raise ValueError(f"need at least {slow + 1} bars, got {len(bars)}")

    closes = [float(b["close"]) for b in bars]
    dates = [str(b.get("datetime") or b.get("date") or i) for i, b in enumerate(bars)]

    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    position = 0  # 0 flat, 1 long
    trades = 0
    curve: list[dict[str, Any]] = []
    prev_fast: float | None = None
    prev_slow: float | None = None

    for i, close in enumerate(closes):
        f = _sma(closes, i, fast)
        s = _sma(closes, i, slow)

        if f is not None and s is not None and prev_fast is not None and prev_slow is not None:
            # 金叉：短线上穿长线 → 买入
            if prev_fast <= prev_slow and f > s and position == 0:
                position = 1
                trades += 1
            # 死叉：短线下穿长线 → 卖出
            elif prev_fast >= prev_slow and f < s and position == 1:
                position = 0
                trades += 1

        if i > 0 and position == 1:
            daily_ret = close / closes[i - 1] - 1.0
            equity *= 1.0 + daily_ret

        peak = max(peak, equity)
        dd = equity / peak - 1.0
        max_dd = min(max_dd, dd)

        curve.append(
            {
                "date": dates[i],
                "equity": round(equity, 6),
                "close": close,
                "fast_ma": None if f is None else round(f, 4),
                "slow_ma": None if s is None else round(s, 4),
                "position": position,
            }
        )
        prev_fast, prev_slow = f, s

    return DualMaResult(
        equity_curve=curve,
        cum_return=round(equity - 1.0, 6),
        max_drawdown=round(max_dd, 6),
        trades=trades,
        bars_used=len(bars),
    )
