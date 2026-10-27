"""akshare-ingest 公共工具。"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

SOURCE = "akshare"


def env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)).strip() or default)
    except ValueError:
        return default


def sleep_ms(default_ms: float | None = None) -> None:
    ms = float(os.environ.get("AKSHARE_INGEST_SLEEP_MS", str(default_ms or 800)))
    time.sleep(max(0.05, ms / 1000.0))


def df_records(df: Any) -> list[dict[str, Any]]:
    if df is None:
        return []
    try:
        if getattr(df, "empty", False):
            return []
        return df.to_dict(orient="records")
    except Exception:
        return []


def _is_transient_upstream(exc: BaseException) -> bool:
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    needles = (
        "remotedisconnected",
        "connection aborted",
        "connection reset",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "max retries",
        "503",
        "502",
        "429",
    )
    if any(n in msg for n in needles):
        return True
    if any(n in name for n in ("timeout", "connection", "protocol")):
        return True
    return False


def call_ak(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """调用 akshare；连接类错误最多 3 次指数退避，仍失败返回 None。"""
    name = getattr(fn, "__name__", str(fn))
    retries = max(1, int_env("AKSHARE_INGEST_CALL_RETRIES", 3))
    last_exc: BaseException | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < retries and _is_transient_upstream(exc):
                backoff = min(8.0, 0.5 * (2 ** (attempt - 1)))
                print(
                    f"akshare-ingest call {name} retry {attempt}/{retries} "
                    f"after {backoff:.1f}s: {exc}",
                    flush=True,
                )
                time.sleep(backoff)
                continue
            print(f"akshare-ingest call {name} failed: {exc}", flush=True)
            return None
    if last_exc is not None:
        print(f"akshare-ingest call {name} failed: {last_exc}", flush=True)
    return None


def day_s(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().replace("/", "-")
    if not s:
        return None
    # 20241027 → 2024-10-27
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8 and "-" not in s[:10]:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return s[:10]


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_shares(value: Any) -> float | None:
    """股本：若像「亿」量级小数则 ×1e8；否则当股。"""
    v = to_float(value)
    if v is None:
        return None
    if abs(v) < 1e7:  # 常见上游用「万股/亿股」混杂；<1e7 视为亿→股
        # 个股总股本常见 几亿～几百亿股；若给的是「亿」则 几～几百
        if abs(v) < 5000:
            return v * 1e8
    return v
