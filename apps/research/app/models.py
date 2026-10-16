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
    factor: str = Field(default="momentum", description="因子名，如 momentum")
    windowYears: int = Field(default=3, ge=1, le=10, description="回看年数")


class BacktestRequest(BaseModel):
    strategy: str = Field(default="dual_ma", description="策略标识")
    fast: int = Field(default=20, description="快均线周期")
    slow: int = Field(default=60, description="慢均线周期")
    universe: str = Field(default="000300.SH", description="标的或指数宇宙")
