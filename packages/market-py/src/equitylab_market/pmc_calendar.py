"""pandas_market_calendars → market.trading_calendar。

权威日历源（今年 + 明年）：pip 包 pandas_market_calendars（~1k★）。
- A 股休市三所一致：SSE/SZSE/BSE 都用库内日历名 ``SSE``（勿用 ``BSE``——那是孟买）。
- ``XSHG`` 对未公布年份常退化为纯工作日；优先 ``SSE``。
- 依赖为可选：未安装时 sync 返回 0 并由调用方 seed。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from equitylab_market import pg as pg_market

SOURCE = "pmc"
# EquityLab 交易所 → pandas_market_calendars 注册名
_PMC_NAME_BY_EXCHANGE: dict[str, str] = {
    "SSE": "SSE",
    "SZSE": "SSE",
    "BSE": "SSE",
}
_DEFAULT_EXCHANGES = ("SSE", "SZSE", "BSE")


def _weekday_count(year: int) -> int:
    d = date(year, 1, 1)
    end = date(year, 12, 31)
    n = 0
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def trading_days_for_year(year: int, *, pmc_name: str = "SSE") -> set[date]:
    """某年交易日集合；库不可用或区间无会话时返回空集。"""
    try:
        import pandas_market_calendars as mcal
    except ImportError as exc:
        raise RuntimeError(
            "pandas_market_calendars 未安装；adata-ingest 须 pip 依赖该包"
        ) from exc
    cal = mcal.get_calendar(pmc_name)
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    schedule = cal.schedule(start_date=start, end_date=end)
    out: set[date] = set()
    for ts in schedule.index:
        if hasattr(ts, "date"):
            out.add(ts.date())
        else:
            out.add(date.fromisoformat(str(ts)[:10]))
    return out


def year_looks_unpublished(trading_days: set[date], year: int) -> bool:
    """会话数≈全年工作日 → 视为尚未写入真实节假日（常见于明年）。"""
    if not trading_days:
        return True
    return len(trading_days) >= _weekday_count(year)


def apply_calendar_year_from_pmc(
    exchange_code: str,
    year: int,
    *,
    pmc_name: str | None = None,
    source_code: str = SOURCE,
    skip_if_unpublished: bool = True,
) -> int:
    """整年 replace 写入；未公布年份可跳过（留给 seed-insert）。"""
    name = pmc_name or _PMC_NAME_BY_EXCHANGE.get(exchange_code, "SSE")
    days = trading_days_for_year(year, pmc_name=name)
    if not days:
        return 0
    if skip_if_unpublished and year > date.today().year and year_looks_unpublished(
        days, year
    ):
        return 0
    return pg_market.apply_calendar_year_from_trading_days(
        exchange_code,
        days,
        year=year,
        source_code=source_code,
    )


def sync_cn_equity_calendar(
    *,
    years: tuple[int, ...] | list[int] | None = None,
    exchanges: tuple[str, ...] = _DEFAULT_EXCHANGES,
    source_code: str = SOURCE,
) -> dict[str, Any]:
    """写今年+明年（可覆盖 years）；返回计数与跳过原因。"""
    y0 = date.today().year
    year_list = list(years) if years is not None else [y0, y0 + 1]
    total = 0
    detail: list[dict[str, Any]] = []
    for year in year_list:
        try:
            days = trading_days_for_year(year, pmc_name="SSE")
        except Exception as exc:
            detail.append({"year": year, "error": str(exc), "n": 0})
            continue
        unpublished = year_looks_unpublished(days, year) and year > y0
        if not days or unpublished:
            detail.append(
                {
                    "year": year,
                    "skipped": "unpublished" if unpublished or not days else "empty",
                    "trading_days": len(days),
                    "n": 0,
                }
            )
            continue
        for ex in exchanges:
            n = pg_market.apply_calendar_year_from_trading_days(
                ex, days, year=year, source_code=source_code
            )
            total += n
            detail.append(
                {
                    "year": year,
                    "exchange": ex,
                    "trading_days": len(days),
                    "n": n,
                }
            )
    return {"total": total, "detail": detail, "source_code": source_code}
