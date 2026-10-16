//! 交易所适配层（多交易所扩展 seam）。
//!
//! 每个交易所是独立**深模块**：对外只暴露 `id` / `router` / `provider`，
//! 实现细节（REST 字段、WS 帧）留在子目录内。
//!
//! 新增交易所步骤：
//! 1. 新增 `exchanges/<name>/`（client + http + ws + provider）
//! 2. 在 [`registry`] 登记 `id` 与挂载路径
//! 3. 在 `main` 里构造模块、挂路由，并按需接入 `MARKET_PROVIDER`
//!
//! 统一 Quote/Bars 仍走 [`crate::providers::MarketDataProvider`]；
//! 交易所原生能力挂在 `/exchanges/{id}/*`（币安另保留 `/binance` 别名）。

pub mod binance;

use axum::{routing::get, Json, Router};
use serde_json::{json, Value};

/// 已注册交易所元数据（给 `/exchanges` 目录用）。
pub fn registry() -> Value {
    json!({
        "exchanges": [
            {
                "id": binance::ID,
                "name": "Binance Spot Public",
                "auth": "none",
                "mounts": ["/exchanges/binance", "/binance"],
                "provider": "binance",
                "docs": "docs/2026-10-16-binance-market.md"
            }
        ],
        "note": "后续 OKX / Bybit 等在 exchanges/ 下按同构模块接入"
    })
}

async fn exchanges_catalog() -> Json<Value> {
    Json(registry())
}

/// 挂载交易所路由；`binance` 由调用方构造以便与统一 Provider 共享 Client。
pub fn mount_exchange_routes(binance: &binance::BinanceModule) -> Router {
    Router::new()
        .route("/exchanges", get(exchanges_catalog))
        .route("/exchanges/", get(exchanges_catalog))
        .nest("/exchanges/binance", binance.router())
        .nest("/binance", binance.router())
}
