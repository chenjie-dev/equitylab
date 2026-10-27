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
    ms = float(os.environ.get("AKSHARE_INGEST_SLEEP_MS", str(default_ms or 350)))
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


def call_ak(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """调用 akshare；失败返回 None。"""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        name = getattr(fn, "__name__", str(fn))
        print(f"akshare-ingest call {name} failed: {exc}", flush=True)
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
