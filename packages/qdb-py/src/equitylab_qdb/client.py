from __future__ import annotations

import os
import time
from typing import Any

import requests

PRICE_SCALE = 10_000


def scale(value: Any) -> int:
    return int(round(float(value) * PRICE_SCALE))


def unscale(raw: Any) -> float:
    try:
        return float(raw) / PRICE_SCALE
    except (TypeError, ValueError):
        return 0.0


class Client:
    """同步 HTTP 客户端。base_url 默认 `QDB_URL` 或 `http://qdb:9090`。"""

    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (
            base_url or os.environ.get("QDB_URL") or "http://qdb:9090"
        ).rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    def wait_ready(self, timeout: float = 60.0, interval: float = 1.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                r = self._session.get(
                    f"{self.base_url}/v1/snapshots", timeout=min(2.0, self.timeout)
                )
                if r.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(interval)
        return False

    def snapshots(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {}
        if symbols:
            params["symbols"] = ",".join(symbols)
        r = self._session.get(
            f"{self.base_url}/v1/snapshots",
            params=params or None,
            timeout=self.timeout,
        )
        r.raise_for_status()
        body = r.json()
        return list(body.get("data") or [])

    def snapshots_body(self, symbols: list[str] | None = None) -> dict[str, Any]:
        """返回完整 JSON（含 scale / source），供 research 包装。"""
        params: dict[str, str] = {}
        if symbols:
            params["symbols"] = ",".join(symbols)
        try:
            r = self._session.get(
                f"{self.base_url}/v1/snapshots",
                params=params or None,
                timeout=min(2.5, self.timeout),
            )
            r.raise_for_status()
            return r.json()
        except Exception:
            return {"data": [], "source": "qdb", "error": "qdb_unavailable"}

    def klines(self, symbol: str, period: str) -> list[dict[str, Any]]:
        try:
            r = self._session.get(
                f"{self.base_url}/v1/klines",
                params={"symbol": symbol, "period": period},
                timeout=self.timeout,
            )
            if r.status_code == 404:
                return []
            r.raise_for_status()
            return list(r.json().get("data") or [])
        except Exception:
            return []

    def get_doc(self, key: str) -> Any | None:
        try:
            r = self._session.get(
                f"{self.base_url}/v1/docs",
                params={"key": key},
                timeout=self.timeout,
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def put_docs(self, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        r = self._session.post(
            f"{self.base_url}/v1/docs",
            json={"items": items},
            timeout=max(self.timeout, 30.0),
        )
        r.raise_for_status()
        return int(r.json().get("written") or 0)

    def post_quotes(self, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        r = self._session.post(
            f"{self.base_url}/v1/quotes",
            json={"items": items},
            timeout=max(self.timeout, 60.0),
        )
        r.raise_for_status()
        return int(r.json().get("written") or 0)

    def post_trades(self, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0
        r = self._session.post(
            f"{self.base_url}/v1/trades",
            json={"items": items},
            timeout=max(self.timeout, 120.0),
        )
        r.raise_for_status()
        return int(r.json().get("written") or 0)

    def post_json(self, path: str, body: dict[str, Any], timeout: float | None = None) -> Any:
        """兼容旧 collector `post(path, body)`。"""
        r = self._session.post(
            f"{self.base_url}{path}",
            json=body,
            timeout=timeout if timeout is not None else max(self.timeout, 120.0),
        )
        r.raise_for_status()
        if r.content:
            try:
                return r.json()
            except Exception:
                return None
        return None
