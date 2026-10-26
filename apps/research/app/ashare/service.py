"""A 股读路径：全市场代码 / 实时行情 / K 线 / 五档，一律只读 qdb。"""

from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd

logger = logging.getLogger("equitylab.research.ashare")

# k_type：1日 2周 3月；分钟：5/15/30/60
KTYPE_MAP = {
    "1d": 1,
    "1w": 2,
    "1M": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "60m": 60,
    "1h": 60,
}

_SEED_CODES: list[dict[str, Any]] = [
    {"stock_code": "600519", "short_name": "贵州茅台", "exchange": "SH", "symbol": "600519.SH"},
    {"stock_code": "000001", "short_name": "平安银行", "exchange": "SZ", "symbol": "000001.SZ"},
    {"stock_code": "300750", "short_name": "宁德时代", "exchange": "SZ", "symbol": "300750.SZ"},
    {"stock_code": "601318", "short_name": "中国平安", "exchange": "SH", "symbol": "601318.SH"},
    {"stock_code": "000858", "short_name": "五粮液", "exchange": "SZ", "symbol": "000858.SZ"},
    {"stock_code": "002594", "short_name": "比亚迪", "exchange": "SZ", "symbol": "002594.SZ"},
    {"stock_code": "600036", "short_name": "招商银行", "exchange": "SH", "symbol": "600036.SH"},
    {"stock_code": "601012", "short_name": "隆基绿能", "exchange": "SH", "symbol": "601012.SH"},
    {"stock_code": "688981", "short_name": "中芯国际", "exchange": "SH", "symbol": "688981.SH"},
    {"stock_code": "510300", "short_name": "沪深300ETF", "exchange": "SH", "symbol": "510300.SH"},
    {"stock_code": "000568", "short_name": "泸州老窖", "exchange": "SZ", "symbol": "000568.SZ"},
    {"stock_code": "600900", "short_name": "长江电力", "exchange": "SH", "symbol": "600900.SH"},
    {"stock_code": "601899", "short_name": "紫金矿业", "exchange": "SH", "symbol": "601899.SH"},
    {"stock_code": "300059", "short_name": "东方财富", "exchange": "SZ", "symbol": "300059.SZ"},
    {"stock_code": "002475", "short_name": "立讯精密", "exchange": "SZ", "symbol": "002475.SZ"},
    {"stock_code": "600276", "short_name": "恒瑞医药", "exchange": "SH", "symbol": "600276.SH"},
    {"stock_code": "000333", "short_name": "美的集团", "exchange": "SZ", "symbol": "000333.SZ"},
    {"stock_code": "601166", "short_name": "兴业银行", "exchange": "SH", "symbol": "601166.SH"},
    {"stock_code": "600030", "short_name": "中信证券", "exchange": "SH", "symbol": "600030.SH"},
    {"stock_code": "002415", "short_name": "海康威视", "exchange": "SZ", "symbol": "002415.SZ"},
]


def _df_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    out = df.copy()
    # 时间列转字符串，NaN → None
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].astype(str)
    out = out.where(pd.notnull(out), None)
    return out.to_dict(orient="records")


class AshareService:
    """进程内短 TTL 缓存（只缓存已从 qdb 读到的结果）。"""

    def __init__(self) -> None:
        self._codes: list[dict[str, Any]] | None = None
        self._codes_at = 0.0
        self._codes_ttl = 3600.0
        self._quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._quote_ttl = 5.0

    def list_codes(self, q: str | None = None, limit: int = 5000) -> dict[str, Any]:
        now = time.monotonic()
        source = "qdb"
        if self._codes is None or now - self._codes_at > self._codes_ttl:
            from app.ashare.qdb_client import snapshots_all

            by_code = {row["stock_code"]: dict(row) for row in _SEED_CODES}
            for row in snapshots_all().get("data") or []:
                code = str(row.get("stock_code") or "").zfill(6)
                if not code or code == "000000":
                    continue
                exchange = "SH" if str(row.get("exchange") or "").startswith("SS") or code.startswith(("5", "6", "9")) else "SZ"
                if str(row.get("exchange") or "") == "SZSE":
                    exchange = "SZ"
                elif str(row.get("exchange") or "") == "SSE":
                    exchange = "SH"
                by_code[code] = {
                    "stock_code": code,
                    "short_name": row.get("short_name") or by_code.get(code, {}).get("short_name", ""),
                    "exchange": exchange,
                    "symbol": f"{code}.{exchange}",
                }
            self._codes = list(by_code.values())
            self._codes_at = now

        rows = self._codes or list(_SEED_CODES)
        if q:
            qq = q.strip().upper()
            rows = [
                r
                for r in rows
                if qq in r["stock_code"]
                or qq in str(r["short_name"]).upper()
                or qq in r["symbol"]
            ]
        total = len(rows)
        if limit > 0:
            rows = rows[:limit]
        return {"count": total, "data": rows, "source": source}

    @staticmethod
    def _normalize_codes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        norm: list[dict[str, Any]] = []
        for r in rows:
            code = str(r.get("stock_code") or r.get("code") or "").zfill(6)
            if not code or code == "000000":
                continue
            name = r.get("short_name") or r.get("name") or ""
            exchange = r.get("exchange") or r.get("market") or ""
            if not exchange:
                if code.startswith(("5", "6", "9")):
                    exchange = "SH"
                else:
                    exchange = "SZ"
            norm.append(
                {
                    "stock_code": code,
                    "short_name": name,
                    "exchange": str(exchange).upper(),
                    "symbol": f"{code}.{str(exchange).upper()}",
                }
            )
        return norm

    def quotes(self, codes: list[str]) -> dict[str, Any]:
        """实时报价只读 qdb。采集由 collector 写入。"""
        from app.ashare.qdb_client import snapshots

        clean = []
        for c in codes:
            c = "".join(ch for ch in str(c).strip() if ch.isdigit())
            if len(c) >= 6:
                clean.append(c[-6:].zfill(6))
            elif c:
                clean.append(c.zfill(6))
        clean = list(dict.fromkeys(clean))[:80]
        if not clean:
            return {"data": [], "source": "qdb"}

        now = time.monotonic()
        cached: list[dict[str, Any]] = []
        missing: list[str] = []
        for code in clean:
            hit = self._quote_cache.get(code)
            if hit and now - hit[0] < self._quote_ttl:
                cached.append(hit[1])
            else:
                missing.append(code)

        if missing:
            fetched = snapshots(missing)
            for row in fetched.get("data") or []:
                code = str(row.get("stock_code") or "").zfill(6)
                self._quote_cache[code] = (now, row)
                cached.append(row)

        by = {r["stock_code"]: r for r in cached}
        ordered = [by[c] for c in clean if c in by]
        return {"data": ordered, "source": "qdb"}

    def klines(
        self,
        stock_code: str,
        k_type: str = "1d",
        start_date: str | None = None,
        end_date: str | None = None,
        adjust_type: int = 1,
        limit: int = 300,
        view: str = "merged",
    ) -> dict[str, Any]:
        """Wind 风格：历史(WSD)与实时(WSQ)分离，再按需合并。

        - history：仅已收盘/已完成 bar
        - realtime：当日快照合成的未完成 bar（盘中）
        - merged：history + realtime（默认，供图表）
        - view：history | realtime | merged
        """
        code = "".join(ch for ch in stock_code if ch.isdigit())[-6:].zfill(6)
        view = (view or "merged").lower()
        if view not in ("history", "realtime", "merged"):
            view = "merged"

        raw_source = "qdb"
        candles = _candles_from_qdb(code, k_type, limit)

        session = _cn_session_status()
        today = session["trade_date"]
        in_session = session["status"] in ("pre", "trading", "lunch", "post")
        is_daily = k_type in ("1d", "1w", "1M")

        history: list[dict[str, Any]] = []
        realtime_block: dict[str, Any] | None = None

        if is_daily:
            # —— 日/周/月：类 Wind WSD；盘中当日未完成 bar 剔出历史 ——
            for c in candles:
                d = str(c.get("trade_date") or "")[:10]
                if not d or d < today:
                    history.append(c)
                elif d == today and not in_session:
                    history.append(c)
                # d == today 且盘中：不进 history

            # —— 类 Wind WSQ：快照合成当日未完成 bar ——
            need_rt = in_session or (
                session["status"] == "closed"
                and session["weekday"]
                and not any(str(c.get("trade_date") or "")[:10] == today for c in history)
            )
            if need_rt:
                snap = _snapshot_qdb(code)
                if snap and snap.get("price") is not None:
                    bar = _realtime_bar_from_snap(snap, today, k_type=k_type)
                    realtime_block = {
                        "bar": bar,
                        "quote": snap,
                        "session": session["status"],
                        "as_of": session["as_of"],
                        "source": "qdb",
                        "kind": "wsq_snapshot",
                    }
        else:
            # —— 分钟：类 Wind WSI；已完成分钟进 history，末根未完成标 realtime ——
            if in_session and candles:
                last = candles[-1]
                last_d = str(last.get("trade_date") or "")[:10]
                if last_d == today:
                    history = list(candles[:-1])
                    last = {**last, "bar_kind": "realtime"}
                    realtime_block = {
                        "bar": last,
                        "quote": None,
                        "session": session["status"],
                        "as_of": session["as_of"],
                        "source": raw_source,
                        "kind": "wsi_open_bar",
                    }
                else:
                    history = list(candles)
            else:
                history = list(candles)

        merged = list(history)
        if realtime_block and realtime_block.get("bar"):
            # 闭市且历史已有当日：realtime 仅作对照，不并入图
            if not (
                is_daily
                and session["status"] == "closed"
                and any(str(c.get("trade_date") or "")[:10] == today for c in history)
            ):
                merged.append(realtime_block["bar"])

        payload: dict[str, Any] = {
            "stock_code": code,
            "k_type": k_type,
            "adjust_type": adjust_type,
            "view": view,
            "session": session,
            "history": {
                "count": len(history),
                "data": history,
                "source": raw_source,
                "note": "已完成 K 线（类 Wind WSD / 已收盘分钟）；不含盘中未完成 bar",
            },
            "realtime": realtime_block,
            "merged": {
                "count": len(merged),
                "data": merged,
                "note": "history + realtime（类 Wind 图：WSD+WSQ / WSI）",
            },
            # 兼容旧前端：data = 按 view 选择
            "count": 0,
            "data": [],
            "source": raw_source,
        }
        if view == "history":
            payload["data"] = history
            payload["count"] = len(history)
        elif view == "realtime":
            bar = realtime_block["bar"] if realtime_block else None
            payload["data"] = [bar] if bar else []
            payload["count"] = len(payload["data"])
            payload["source"] = (
                realtime_block["source"] if realtime_block else raw_source
            )
        else:
            payload["data"] = merged
            payload["count"] = len(merged)
        return payload

    def five(self, stock_code: str) -> dict[str, Any]:
        from app.ashare.qdb_client import snapshots

        code = "".join(ch for ch in stock_code if ch.isdigit())[-6:].zfill(6)
        return {
            "stock_code": code,
            "data": snapshots([code]).get("data") or [],
            "source": "qdb",
        }

    def intraday(self, stock_code: str) -> dict[str, Any]:
        code = "".join(ch for ch in stock_code if ch.isdigit())[-6:].zfill(6)
        candles = _candles_from_qdb(code, "5m", 240)
        return {
            "stock_code": code,
            "data": candles,
            "source": "qdb",
        }


def _candles_from_qdb(code: str, k_type: str, limit: int) -> list[dict[str, Any]]:
    """K 线只从 qdb 读（窗口 limit）。周/月由日线归并，30 分由 15 分两两归并。"""
    from datetime import datetime, timezone

    from app.ashare.qdb_client import klines as qdb_klines
    from app.ashare.qdb_client import qdb_symbol

    period = {"1w": "1d", "1M": "1d", "30m": "15m", "60m": "1h", "1h": "1h"}.get(k_type, k_type)
    if period not in ("1d", "5m", "15m", "1h"):
        period = "1d"
    # 折叠会吞原生桶；多取一点，且不超过 qdb HTTP 上限 5000
    fold = {"30m": 2, "1w": 7, "1M": 31}.get(k_type, 1)
    want = max(1, int(limit) if limit > 0 else 300)
    raw_limit = min(5000, want * fold + fold)
    candles: list[dict[str, Any]] = []
    for row in qdb_klines(qdb_symbol(code), period, limit=raw_limit):
        ts = row.get("ts")
        if ts is None:
            continue
        ms = int(ts) // 1_000_000
        day = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        candles.append(
            {
                "time": ms,
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "trade_date": day,
                "bar_kind": "realtime" if int(row.get("state") or 1) == 0 else "history",
            }
        )
    if k_type == "30m":
        candles = _fold_pairs(candles)
    elif k_type == "1w":
        candles = _fold_dates(candles, 7)
    elif k_type == "1M":
        candles = _fold_month(candles)
    if limit > 0:
        candles = candles[-limit:]
    return candles


def _fold_pairs(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(0, len(candles), 2):
        chunk = candles[i : i + 2]
        out.append(_merge_bars(chunk))
    return out


def _fold_dates(candles: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    chunk: list[dict[str, Any]] = []
    for bar in candles:
        if chunk and len(chunk) >= days:
            out.append(_merge_bars(chunk))
            chunk = []
        chunk.append(bar)
    if chunk:
        out.append(_merge_bars(chunk))
    return out


def _fold_month(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    key = ""
    for bar in candles:
        month = str(bar.get("trade_date") or "")[:7]
        if month != key:
            groups.append([])
            key = month
        groups[-1].append(bar)
    return [_merge_bars(g) for g in groups if g]


def _merge_bars(chunk: list[dict[str, Any]]) -> dict[str, Any]:
    first, last = chunk[0], chunk[-1]
    highs = [float(b["high"]) for b in chunk if b.get("high") is not None]
    lows = [float(b["low"]) for b in chunk if b.get("low") is not None]
    volume = sum(float(b.get("volume") or 0) for b in chunk)
    return {
        "time": first.get("time"),
        "open": first.get("open"),
        "high": max(highs) if highs else first.get("high"),
        "low": min(lows) if lows else first.get("low"),
        "close": last.get("close"),
        "volume": volume,
        "trade_date": last.get("trade_date"),
        "bar_kind": last.get("bar_kind"),
    }


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_ts_ms(s: str) -> int | None:
    """解析为 UTC 毫秒时间戳（日 K 用当日 00:00 UTC，避免容器时区错位）。"""
    if not s or s == "None":
        return None
    from datetime import datetime, timezone

    s = s.strip().replace("T", " ")
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            raw = s[:n]
            dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None


def _to_candle(r: dict[str, Any], bar_kind: str = "history") -> dict[str, Any]:
    trade_date = str(r.get("trade_date") or r.get("day") or "")[:10]
    trade_time = str(r.get("trade_time") or "")
    ts_ms = _parse_ts_ms(trade_time or trade_date)
    return {
        "time": ts_ms,
        "open": _num(r.get("open")),
        "high": _num(r.get("high")),
        "low": _num(r.get("low")),
        "close": _num(r.get("close")),
        "volume": _num(r.get("volume")),
        "trade_date": trade_date or None,
        "change_pct": r.get("change_pct"),
        "bar_kind": bar_kind,
    }


def _cn_session_status() -> dict[str, Any]:
    """A 股交易时段（上海时区），对齐 Wind 盘中/盘后语义。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    hm = now.hour * 100 + now.minute
    weekday = now.weekday() < 5  # Mon-Fri
    trade_date = now.strftime("%Y-%m-%d")
    status = "closed"
    if weekday:
        if 915 <= hm < 930:
            status = "pre"
        elif 930 <= hm < 1130:
            status = "trading"
        elif 1130 <= hm < 1300:
            status = "lunch"
        elif 1300 <= hm < 1500:
            status = "trading"
        elif 1500 <= hm < 1530:
            status = "post"
        else:
            status = "closed"
    return {
        "trade_date": trade_date,
        "status": status,
        "weekday": weekday,
        "as_of": now.isoformat(),
        "tz": "Asia/Shanghai",
    }


def _snapshot_qdb(code: str) -> dict[str, Any] | None:
    """盘中 bar 用的快照，只从 qdb 读。"""
    from app.ashare.qdb_client import snapshots

    body = snapshots([code])
    rows = body.get("data") or []
    if not rows:
        return None
    row = rows[0]
    if row.get("price") is None:
        return None
    return {
        "stock_code": str(row.get("stock_code") or code).zfill(6),
        "short_name": row.get("short_name") or "",
        "open": row.get("open"),
        "pre_close": row.get("pre_close"),
        "price": row.get("price"),
        "high": row.get("high"),
        "low": row.get("low"),
        "volume": row.get("volume"),
        "amount": row.get("amount"),
        "trade_date": None,
        "trade_time": None,
    }


def _realtime_bar_from_snap(
    snap: dict[str, Any], today: str, k_type: str = "1d"
) -> dict[str, Any]:
    """用 WSQ 快照合成当日未完成 bar。"""
    trade_date = str(snap.get("trade_date") or today)[:10] or today
    # 日/周/月：用自然日 00:00 UTC；分钟周期用快照时刻
    if k_type in ("5m", "15m", "30m", "60m", "1h") and snap.get("trade_time"):
        ts_raw = f"{trade_date} {snap['trade_time']}"
    else:
        ts_raw = trade_date
    open_ = snap.get("open") or snap.get("price")
    high = snap.get("high") or snap.get("price")
    low = snap.get("low") or snap.get("price")
    close = snap.get("price")
    pre = snap.get("pre_close")
    chg_pct = None
    if close is not None and pre not in (None, 0):
        chg_pct = round((float(close) - float(pre)) / float(pre) * 100, 2)
    return {
        "time": _parse_ts_ms(ts_raw),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": snap.get("volume"),
        "trade_date": trade_date,
        "change_pct": chg_pct,
        "bar_kind": "realtime",
    }


# 单例，供 router 使用
service = AshareService()
