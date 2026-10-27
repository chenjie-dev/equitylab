"""Pydantic 请求/响应模型（公共契约）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthBody(BaseModel):
    status: str = "UP"
    service: str = "research"
    ts: str


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1, description="自然语言查询或关键词")
    top_k: int = Field(default=5, ge=1, le=20, description="召回条数上限")


class FactorIcRequest(BaseModel):
    factor: str = Field(default="momentum", description="目前仅支持 momentum（时序）")
    windowYears: int = Field(default=3, ge=1, le=10, description="回看年数 → 拉取日线根数")
    universe: str = Field(
        default="600519",
        description="单标的：600519 / 600519.SH / SSE:600519",
    )
    lookback: int = Field(default=20, ge=1, le=120, description="动量回看交易日")
    horizon: int = Field(default=5, ge=1, le=60, description="前瞻收益交易日")


class BacktestRequest(BaseModel):
    strategy: str = Field(default="dual_ma", description="策略标识")
    fast: int = Field(default=20, ge=1, le=120, description="快均线周期")
    slow: int = Field(default=60, ge=2, le=250, description="慢均线周期")
    universe: str = Field(default="000300.SH", description="标的或指数宇宙")
    period: str = Field(default="1d", description="K 线周期，传给 market-data")
    count: int = Field(default=120, ge=30, le=500, description="拉取 K 线根数")
    adjust: str = Field(default="none", description="复权：none / qfq / hfq")
