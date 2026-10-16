//! 币安现货公开行情模块（深模块）。
//!
//! # 接口（调用方只需知道这些）
//! - [`ID`] / [`BinanceModule::from_env`]
//! - [`BinanceModule::router`] → `/exchanges/binance/*` 或 `/binance/*`
//! - [`BinanceModule::provider`] → `MARKET_PROVIDER=binance`
//!
//! # 实现
//! `client`（现货 REST）· `rwa`（Ondo 代币化美股）· `http` · `ws` · `provider`

mod client;
mod http;
mod provider;
mod rwa;
mod ws;

pub use client::Client;
pub use provider::Provider;

use axum::{routing::any, routing::get, Router};
use std::sync::Arc;

pub const ID: &str = "binance";

/// 币安模块入口：持有共享 Client，可挂路由或产出统一 Provider。
#[derive(Clone)]
pub struct BinanceModule {
    client: Arc<Client>,
    rwa: Arc<rwa::RwaClient>,
}

impl BinanceModule {
    pub fn from_env() -> Self {
        Self {
            client: Arc::new(Client::from_env()),
            rwa: Arc::new(rwa::RwaClient::from_env()),
        }
    }

    /// 交易所原生 HTTP + WS + RWA；现货与 RWA 使用各自 state。
    pub fn router(&self) -> Router {
        router(self.client.clone(), self.rwa.clone())
    }

    /// 接入统一 [`crate::providers::MarketDataProvider`]。
    pub fn provider(&self) -> Provider {
        Provider::new(self.client.clone())
    }
}

fn router(client: Arc<Client>, rwa_client: Arc<rwa::RwaClient>) -> Router {
    Router::new()
        .route("/", get(http::catalog))
        .route("/ping", get(http::ping))
        .route("/time", get(http::server_time))
        .route("/exchangeInfo", get(http::exchange_info))
        .route("/ticker/24hr", get(http::ticker_24hr))
        .route("/ticker/price", get(http::ticker_price))
        .route("/ticker/bookTicker", get(http::book_ticker))
        .route("/avgPrice", get(http::avg_price))
        .route("/depth", get(http::depth))
        .route("/trades", get(http::trades))
        .route("/aggTrades", get(http::agg_trades))
        .route("/klines", get(http::klines))
        .route("/uiKlines", get(http::ui_klines))
        .route("/v3/{*path}", get(http::proxy_v3))
        .route("/ws", any(ws::ws_upgrade))
        .with_state(client)
        .nest("/rwa", rwa::router(rwa_client))
}
