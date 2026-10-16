//! EquityLab 行情数据服务（Rust / Axum）
//!
//! # 职责
//! - 提供 REST：实时快照、历史 K 线、标的搜索
//! - 通过 [`providers::MarketDataProvider`] 适配多数据源
//! - 实时报价经 Redis 短 TTL 缓存（默认 3s），降低上游配额压力
//!
//! # 环境变量
//! - `PORT`（默认 3002）
//! - `REDIS_URL`（不可用时降级为无缓存直连）
//! - `MARKET_PROVIDER`：`mock`（默认）| `alphafeed`
//!
//! # 后续 TODO
//! TickFlow / AkShare Provider、熔断降级、K 线异步落 PG、独立 WebSocket 推送、Prometheus 指标。

mod cache;
mod handlers;
mod providers;
mod trace;

use axum::{middleware::from_fn, routing::get, Router};
use cache::QuoteCache;
use providers::{mock::MockProvider, MarketDataProvider};
use std::{net::SocketAddr, sync::Arc};
use tower_http::cors::CorsLayer;
use tracing_subscriber::EnvFilter;

/// 行情服务共享状态：当前 Provider 与报价缓存。
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

    let provider: Arc<dyn MarketDataProvider> = match provider_name.as_str() {
        "alphafeed" => Arc::new(providers::alpha_feed::AlphaFeedProvider::from_env()),
        _ => Arc::new(MockProvider::default()),
    };

    // Redis 故障不应阻断本地开发：降级为直连 Provider。
    let cache = QuoteCache::connect(&redis_url).await.unwrap_or_else(|e| {
        tracing::warn!("redis unavailable ({e}); continuing without cache");
        QuoteCache::disabled()
    });

    let state = Arc::new(AppState { provider, cache });
    let app = Router::new()
        .route("/health", get(handlers::health))
        .route("/quotes/{symbol}", get(handlers::get_quote))
        .route("/bars/{symbol}", get(handlers::get_bars))
        .route("/search", get(handlers::search))
        .layer(from_fn(trace::trace_middleware))
        .layer(CorsLayer::permissive())
        .with_state(state);

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
