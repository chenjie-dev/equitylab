"""A 股盘中门禁：读 PG trading_calendar（SSE），进程内缓存。

三所休市一致，只缓存 SSE。库不可用时回落「周一–周五」启发式。
"""

from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

SH = ZoneInfo("Asia/Shanghai")

_lock = threading.Lock()
_trading_days: Optional[set[date]] = None
_loaded_at: float = 0.0
_window_start: Optional[date] = None
_window_end: Optional[date] = None

# 默认每小时刷新；COLLECTOR_CALENDAR_REFRESH_SEC 可改
_REFRESH_SEC = float(os.environ.get("COLLECTOR_CALENDAR_REFRESH_SEC", "3600"))
# 非交易日 poll 间隔（秒）
OFF_SESSION_INTERVAL_SEC = float(
    os.environ.get("COLLECTOR_OFF_SESSION_INTERVAL_SEC", "30")
)


def shanghai_today() -> date:
    return datetime.now(SH).date()


def _weekday_fallback(day: date) -> bool:
    return day.weekday() < 5


def refresh(*, force: bool = False) -> bool:
    """从 PG 拉近窗交易日。成功返回 True。"""
    global _trading_days, _loaded_at, _window_start, _window_end
    now = time.monotonic()
    with _lock:
        if (
            not force
            and _trading_days is not None
            and (now - _loaded_at) < _REFRESH_SEC
        ):
            return True
    try:
        from equitylab_market import pg as pg_market
    except Exception as exc:
        print(f"session_calendar import pg failed: {exc}", flush=True)
        return False
    today = shanghai_today()
    start = today - timedelta(days=14)
    end = today + timedelta(days=21)
    days = pg_market.load_trading_days("SSE", start, end)
    if days is None:
        print("session_calendar: DATABASE_URL 不可用，回落工作日启发式", flush=True)
        return False
    with _lock:
        _trading_days = days
        _window_start = start
        _window_end = end
        _loaded_at = time.monotonic()
    print(
        f"session_calendar loaded SSE trading_days={len(days)} "
        f"window={start}..{end}",
        flush=True,
    )
    return True


def is_cn_session_day(day: date | str | None = None) -> bool:
    """是否 A 股交易日（SSE 日历）。缓存未命中时尝试刷新；仍无则工作日回落。"""
    if day is None:
        d = shanghai_today()
    elif isinstance(day, date):
        d = day
    else:
        d = date.fromisoformat(str(day)[:10])

    with _lock:
        cached = _trading_days
        start, end = _window_start, _window_end
        age_ok = (time.monotonic() - _loaded_at) < _REFRESH_SEC

    if cached is None or not age_ok or start is None or end is None or d < start or d > end:
        refresh()
        with _lock:
            cached = _trading_days

    if cached is None:
        return _weekday_fallback(d)
    # 窗口内无该日行：不当作交易日（权威表应含全年）
    if start is not None and end is not None and start <= d <= end:
        return d in cached
    # 窗外：回落工作日，避免未来远日误杀
    return _weekday_fallback(d)


def poll_interval_sec(base_interval: float) -> float:
    """交易日用 COLLECTOR_INTERVAL；休市日拉长。"""
    if is_cn_session_day():
        return base_interval
    return max(base_interval, OFF_SESSION_INTERVAL_SEC)
