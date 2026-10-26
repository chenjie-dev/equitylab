"""write_gate：quotes 按标的合并，避免积压过期报价覆盖快照。"""

from __future__ import annotations

import time

from write_gate import WriteGate


def test_quotes_coalesce_keeps_latest_per_symbol() -> None:
    posted: list[dict] = []

    def capture(path: str, body: dict) -> None:
        if path.endswith("/quotes"):
            posted.extend(body.get("items") or [])

    gate = WriteGate(capture)
    gate.start()
    # 同一标的连写三次：队列里应只留最后一次
    for price in (100.0, 101.0, 102.5):
        gate.enqueue(
            "/v1/quotes",
            {
                "items": [
                    {
                        "exchange": "SSE",
                        "code": "600519",
                        "last": int(price * 10000),
                        "price": price,
                    }
                ]
            },
            priority="high",
        )
    # 另一标的不丢
    gate.enqueue(
        "/v1/quotes",
        {
            "items": [
                {
                    "exchange": "SZSE",
                    "code": "000001",
                    "last": 11_0000,
                    "price": 11.0,
                }
            ]
        },
        priority="high",
    )
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        codes = {(r.get("exchange"), r.get("code")) for r in posted}
        if codes >= {("SSE", "600519"), ("SZSE", "000001")}:
            break
        time.sleep(0.02)
    maotai = [r for r in posted if r.get("code") == "600519"]
    assert maotai, "expected 600519 quote flushed"
    # 合并后该标的只会刷出最新价（允许同批仅一条）
    assert maotai[-1]["price"] == 102.5
    assert all(r["price"] == 102.5 for r in maotai)


def test_quotes_flushed_before_trades_same_round() -> None:
    """同轮 drain 后先 POST quotes 再 trades。"""
    order: list[str] = []

    def capture(path: str, body: dict) -> None:
        order.append(path)

    gate = WriteGate(capture)
    gate.start()
    gate.enqueue(
        "/v1/trades",
        {
            "items": [
                {"exchange": "SSE", "code": "600519", "price": 1, "volume": 1}
            ]
        },
        priority="high",
    )
    gate.enqueue(
        "/v1/quotes",
        {
            "items": [
                {
                    "exchange": "SSE",
                    "code": "600519",
                    "last": 1,
                    "price": 1.0,
                }
            ]
        },
        priority="high",
    )
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not (
        "/v1/quotes" in order and "/v1/trades" in order
    ):
        time.sleep(0.01)
    assert "/v1/quotes" in order and "/v1/trades" in order
    assert order.index("/v1/quotes") < order.index("/v1/trades")