//! EquityLab API 网关（Rust / Axum）
//!
//! # 职责（MVP）
//! - 统一对外入口：`/health`、`/api/*`、`/v1/*`
//! - 按路径前缀反向代理到编排层 / 研究层 / 行情服务
//! - 按客户端 IP 的滑动窗口限流
//!
//! # 后续 TODO
//! JWT 鉴权、租户 Token 预算、多模型路由计费日志、熔断降级。
//!
//! # 路由约定
//! - `/api/chat`、`/v1/*` → Orchestrator（保留完整路径）
//! - `/api/research/*` → Research（剥掉 `/api/research` 前缀）
//! - `/api/market/*` → Market-Data（剥掉 `/api/market` 前缀）

use axum::{
    body::Body,
    extract::{Request, State},
    http::StatusCode,
    response::Response,
    routing::{any, get},
    Json, Router,
};
use chrono::Utc;
use dashmap::DashMap;
use serde::Serialize;
use std::{
    net::{IpAddr, SocketAddr},
    sync::Arc,
    time::{Duration, Instant},
};
use tower_http::cors::CorsLayer;
use tower_http::trace::TraceLayer;
use tracing_subscriber::EnvFilter;

/// 网关共享状态：上游基址、HTTP 客户端与限流器。
#[derive(Clone)]
struct AppState {
    http: reqwest::Client,
    orchestrator_url: String,
    research_url: String,
    market_data_url: String,
    rate_limiter: Arc<RateLimiter>,
}

/// 滑动窗口限流：每个 IP 在 `window` 内最多 `max_requests` 次。
///
/// 实现为进程内 `DashMap`，多副本部署时需改为 Redis 等共享计数器。
struct RateLimiter {
    window: Duration,
    max_requests: usize,
    buckets: DashMap<IpAddr, Vec<Instant>>,
}

impl RateLimiter {
    fn new(window: Duration, max_requests: usize) -> Self {
        Self {
            window,
            max_requests,
            buckets: DashMap::new(),
        }
    }

    /// 若允许本次请求则记录时间戳并返回 `true`；否则返回 `false`（应由调用方返回 429）。
    fn is_allowed(&self, ip: IpAddr) -> bool {
        let now = Instant::now();
        let mut entry = self.buckets.entry(ip).or_default();
        // 丢掉窗口外的命中，保持桶内仅含有效请求。
        entry.retain(|t| now.duration_since(*t) < self.window);
        if entry.len() >= self.max_requests {
            return false;
        }
        entry.push(now);
        true
    }
}

#[derive(Serialize)]
struct HealthBody {
    status: &'static str,
    service: &'static str,
    ts: String,
}

/// 存活探测；不鉴权、不计入业务限流（当前实现仍走独立路由，未进 `proxy`）。
async fn health() -> Json<HealthBody> {
    Json(HealthBody {
        status: "UP",
        service: "gateway",
        ts: Utc::now().to_rfc3339(),
    })
}

/// 反向代理：限流 → 选上游 → 改写路径 → 转发请求体与安全头。
async fn proxy(
    State(state): State<Arc<AppState>>,
    req: Request,
) -> Result<Response, (StatusCode, String)> {
    let peer = req
        .extensions()
        .get::<axum::extract::ConnectInfo<SocketAddr>>()
        .map(|c| c.0.ip())
        .unwrap_or_else(|| IpAddr::from([127, 0, 0, 1]));

    if !state.rate_limiter.is_allowed(peer) {
        return Err((StatusCode::TOO_MANY_REQUESTS, "rate limit exceeded".into()));
    }

    let path = req.uri().path().to_string();
    let query = req
        .uri()
        .query()
        .map(|q| format!("?{q}"))
        .unwrap_or_default();

    let upstream_base = if path.starts_with("/api/chat") || path.starts_with("/v1/") {
        &state.orchestrator_url
    } else if path.starts_with("/api/research") {
        &state.research_url
    } else if path.starts_with("/api/market") {
        &state.market_data_url
    } else {
        return Err((StatusCode::NOT_FOUND, format!("no route for {path}")));
    };

    // 下游服务暴露原生路径（如 /quotes、/rag/search），需剥掉网关前缀。
    let forward_path = if path.starts_with("/api/market") {
        path.replacen("/api/market", "", 1)
    } else if path.starts_with("/api/research") {
        path.replacen("/api/research", "", 1)
    } else {
        path.clone()
    };
    let forward_path = if forward_path.is_empty() {
        "/".to_string()
    } else {
        forward_path
    };

    let url = format!("{upstream_base}{forward_path}{query}");
    let method = req.method().clone();
    let headers = req.headers().clone();
    // 8MB 上限：防止异常大 body 占满网关内存；流式透传后续再做。
    let body_bytes = axum::body::to_bytes(req.into_body(), 8 * 1024 * 1024)
        .await
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;

    let mut builder = state.http.request(
        reqwest::Method::from_bytes(method.as_str().as_bytes()).unwrap_or(reqwest::Method::GET),
        &url,
    );
    for (k, v) in headers.iter() {
        // Host / Content-Length 由 reqwest 按实际上游重写，避免错路由或长度不一致。
        if k == "host" || k == "content-length" {
            continue;
        }
        if let Ok(v) = v.to_str() {
            builder = builder.header(k.as_str(), v);
        }
    }
    if !body_bytes.is_empty() {
        builder = builder.body(body_bytes.to_vec());
    }

    let upstream = builder
        .send()
        .await
        .map_err(|e| (StatusCode::BAD_GATEWAY, e.to_string()))?;

    let status = StatusCode::from_u16(upstream.status().as_u16())
        .unwrap_or(StatusCode::BAD_GATEWAY);
    let mut response = Response::builder().status(status);
    for (k, v) in upstream.headers().iter() {
        if k == "transfer-encoding" {
            continue;
        }
        response = response.header(k.as_str(), v.as_bytes());
    }
    let bytes = upstream
        .bytes()
        .await
        .map_err(|e| (StatusCode::BAD_GATEWAY, e.to_string()))?;
    response
        .body(Body::from(bytes))
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env().add_directive("info".parse().unwrap()))
        .init();

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(3000);
    let rpm: usize = std::env::var("RATE_LIMIT_PER_MINUTE")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(120);

    let state = Arc::new(AppState {
        http: reqwest::Client::new(),
        orchestrator_url: std::env::var("ORCHESTRATOR_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:8001".into()),
        research_url: std::env::var("RESEARCH_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:8002".into()),
        market_data_url: std::env::var("MARKET_DATA_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:3002".into()),
        rate_limiter: Arc::new(RateLimiter::new(Duration::from_secs(60), rpm)),
    });

    let app = Router::new()
        .route("/health", get(health))
        .route("/api/{*rest}", any(proxy))
        .route("/v1/{*rest}", any(proxy))
        .layer(CorsLayer::permissive())
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!("equitylab-gateway listening on {addr}");
    let listener = tokio::net::TcpListener::bind(addr).await.expect("bind");
    // ConnectInfo 用于限流取真实对端 IP（经 Docker/代理时后续需解析 X-Forwarded-For）。
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await
    .expect("serve");
}
