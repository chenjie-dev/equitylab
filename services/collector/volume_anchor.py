"""Sina 累计成交量 → trade 增量锚定。

须覆盖：
- 跨交易日（含隔夜）
- 跨周（周五→周一）
- 节假日休市后再开（日历日跳跃）
- 同日累计量回落/重置

原则：锚点带 `trade_date`；日期变化或量回落只重锚、不把整段累计量灌进当前 5m。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class VolumeState:
    """单标的成交量锚点。"""

    trade_date: str  # YYYY-MM-DD；未知时可为 ""
    volume: int


def next_volume_anchor(
    prev: Optional[VolumeState],
    vol: int,
    *,
    trade_date: Optional[str] = None,
    clock_date: Optional[str] = None,
) -> Tuple[VolumeState, int, str]:
    """返回 (新状态, 本拍 trade 增量, 原因)。

    原因：`first` | `date_change` | `clock_rollover` | `vol_reset` | `delta`
    """
    vol = int(vol)
    td = (trade_date or "").strip()[:10] or None
    clock = (clock_date or "").strip()[:10] or None

    if prev is None:
        return VolumeState(td or clock or "", vol), 0, "first"

    prev_td = (prev.trade_date or "").strip()[:10]
    # 上游给出的交易日前进（跨天 / 跨周 / 节假日后首根）
    if td and prev_td and td != prev_td:
        return VolumeState(td, vol), 0, "date_change"

    # 本地上海日已前进，但量未涨（休市冻结行情仍报旧累计量）：重锚，避免假增量
    if clock and prev_td and prev_td < clock and vol <= prev.volume:
        return VolumeState(clock, vol), 0, "clock_rollover"

    if vol < prev.volume:
        return VolumeState(td or prev_td or clock or "", vol), 0, "vol_reset"

    delta = vol - prev.volume
    return VolumeState(td or prev_td or clock or "", vol), delta, "delta"
