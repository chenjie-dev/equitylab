//! EquityLab 行情数据服务（Rust / Axum）
//!
//! # 职责
//! - 统一 REST：`/quotes` `/bars` `/search`（经 [`providers::MarketDataProvider`]）
//! - 多交易所原生模块：[`exchanges`]（币安已落地，可扩展 OKX 等）
//! - 实时报价 Redis TTL≈3s
//!
//! # 环境变量
//! - `PORT`（默认 3002）
//! - `REDIS_URL`
//! - `MARKET_PROVIDER`：`mock` | `binance`（读 qdb）；`alphafeed` 保留但拒绝外呼
//! - `BINANCE_REST_URL` / `BINANCE_WS_URL`
//! - `QDB_URL`：只读行情与 `/qdb/ws` 代理目标

mod cache;
mod exchanges;
mod handlers;
mod http_metrics;
mod providers;
mod qdb_read;
mod qdb_ws;
mod trace;

use axum::{middleware::from_fn, routing::get, Router};
use cache::QuoteCache;
use exchanges::binance::BinanceModule;
use providers::{mock::MockProvider, MarketDataProvider};
use std::{net::SocketAddr, sync::Arc};
use tower_http::cors::CorsLayer;
use tracing_subscriber::EnvFilter;

/// 统一行情状态（交易所原生路由使用各自模块 state）。
pub struct AppState {
    pub provider: Arc<dyn MarketDataProvider>,
    pub cache: QuoteCache,
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(EnvFilter::from_default_env().add_directive("info".parse().unwrap()))
        .with_current_span(false)
        .with_span_list(false)
        .flatten_event(true)
        .init();

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(3002);
    let redis_url = std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379".into());
    let provider_name = std::env::var("MARKET_PROVIDER").unwrap_or_else(|_| "mock".into());

    let binance_mod = BinanceModule::from_env();

    let provider: Arc<dyn MarketDataProvider> = match provider_name.as_str() {
        "alphafeed" => Arc::new(providers::alpha_feed::AlphaFeedProvider::from_env()),
        "binance" => Arc::new(binance_mod.provider()),
        _ => Arc::new(MockProvider::default()),
    };

    let cache = QuoteCache::connect(&redis_url).await.unwrap_or_else(|e| {
        tracing::warn!("redis unavailable ({e}); continuing without cache");
        QuoteCache::disabled()
    });

    let _metrics = http_metrics::init("market-data");

    let state = Arc::new(AppState { provider, cache });

    let unified = Router::new()
        .route("/health", get(handlers::health))
        .route("/metrics", get(http_metrics::metrics_handler))
        .route("/quotes/{symbol}", get(handlers::get_quote))
        .route("/bars/{symbol}", get(handlers::get_bars))
        .route("/search", get(handlers::search))
        .with_state(state);

    let qdb_ws_routes = Router::new()
        .route("/qdb/ws", get(qdb_ws::ws_upgrade))
        .route("/exchanges/qdb/ws", get(qdb_ws::ws_upgrade));

    let app = Router::new()
        .merge(unified)
        .merge(exchanges::mount_exchange_routes(&binance_mod))
        .merge(qdb_ws_routes)
        .layer(from_fn(http_metrics::metrics_middleware))
        .layer(from_fn(trace::trace_middleware))
        .layer(CorsLayer::permissive());

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!(
        service = "market-data",
        %addr,
        provider = %provider_name,
        "listening"
    );
    let listener = tokio::net::TcpListener::bind(addr).await.expect("bind");
    axum::serve(listener, app).await.expect("serve");
}
