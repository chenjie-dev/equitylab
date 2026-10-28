//! EquityLab API 网关（Rust / Axum）
//!
//! # 职责（MVP）
//! - **唯一对外入口**：浏览器 HTTP + WebSocket 均经本服务（后续鉴权挂在此）
//! - 按路径前缀反向代理到编排层 / 研究层 / 行情服务 / 前端
//! - 按客户端 IP 的滑动窗口限流
//! - 统一 `X-Trace-Id` 生成/透传 + JSON 结构化日志
//!
//! # 后续 TODO
//! JWT 鉴权、租户 Token 预算、多模型路由计费日志、熔断降级、OTel span 导出。
//!
//! # 路由约定
//! - `/api/chat`、`/v1/*` → Orchestrator（保留完整路径）
//! - `/api/research/*` → Research（剥 `/api/research`）
//! - `/api/cn-equity/*` → Research（改写为 `/cn-equity/*`，产品短路径）
//! - `/api/backtests/*` → Research（改写为 `/backtests/*`）
//! - `/api/market/*` → Market-Data（剥 `/api/market`）；WS：`/api/market/qdb/ws`
//! - 页面 / `_next` / 静态 → Frontend（**不含**业务 API；勿再经 Next BFF 回环）

use axum::{
    body::Body,
    extract::{Request, State},
    http::{HeaderName, HeaderValue, StatusCode},
    middleware::{from_fn, Next},
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
use tracing_subscriber::EnvFilter;

mod http_metrics;
mod ws_proxy;

const TRACE_HEADER: &str = "x-trace-id";

/// 网关共享状态：上游基址、HTTP 客户端与限流器。
#[derive(Clone)]
pub(crate) struct AppState {
    http: reqwest::Client,
    orchestrator_url: String,
    research_url: String,
    pub(crate) market_data_url: String,
    frontend_url: String,
    rate_limiter: Arc<RateLimiter>,
}

/// 滑动窗口限流：每个 IP 在 `window` 内最多 `max_requests` 次。
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

    fn is_allowed(&self, ip: IpAddr) -> bool {
        let now = Instant::now();
        let mut entry = self.buckets.entry(ip).or_default();
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

fn resolve_trace_id(req: &Request) -> String {
    req.headers()
        .get(TRACE_HEADER)
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string())
}

/// 确保请求/响应带 `X-Trace-Id`，并输出 JSON access log。
async fn trace_middleware(mut req: Request, next: Next) -> Response {
    let trace_id = resolve_trace_id(&req);
    if let Ok(hv) = HeaderValue::from_str(&trace_id) {
        req.headers_mut()
            .insert(HeaderName::from_static(TRACE_HEADER), hv);
    }
    let method = req.method().clone();
    let path = req.uri().path().to_string();
    let started = Instant::now();
    let mut res = next.run(req).await;
    if let Ok(hv) = HeaderValue::from_str(&trace_id) {
        res.headers_mut()
            .insert(HeaderName::from_static(TRACE_HEADER), hv);
    }
    tracing::info!(
        traceId = %trace_id,
        service = "gateway",
        method = %method,
        path = %path,
        status = res.status().as_u16(),
        latencyMs = started.elapsed().as_millis() as u64,
        "request"
    );
    res
}

async fn health() -> Json<HealthBody> {
    Json(HealthBody {
        status: "UP",
        service: "gateway",
        ts: Utc::now().to_rfc3339(),
    })
}

enum Upstream {
    Orchestrator,
    Research,
    MarketData,
    Frontend,
}

fn classify(path: &str) -> Upstream {
    if path.starts_with("/api/chat") || path.starts_with("/v1/") {
        Upstream::Orchestrator
    } else if path.starts_with("/api/research")
        || path.starts_with("/api/cn-equity")
        || path.starts_with("/api/backtests")
    {
        Upstream::Research
    } else if path.starts_with("/api/market") {
        Upstream::MarketData
    } else {
        Upstream::Frontend
    }
}

fn rewrite_path(upstream: Upstream, path: &str) -> String {
    let rewritten = match upstream {
        Upstream::Orchestrator => path.to_string(),
        Upstream::Research => {
            if let Some(rest) = path.strip_prefix("/api/research") {
                rest.to_string()
            } else if let Some(rest) = path.strip_prefix("/api/cn-equity") {
                format!("/cn-equity{rest}")
            } else if let Some(rest) = path.strip_prefix("/api/backtests") {
                format!("/backtests{rest}")
            } else {
                path.to_string()
            }
        }
        Upstream::MarketData => path
            .strip_prefix("/api/market")
            .unwrap_or(path)
            .to_string(),
        Upstream::Frontend => path.to_string(),
    };
    if rewritten.is_empty() {
        "/".to_string()
    } else {
        rewritten
    }
}

fn skip_rate_limit(path: &str) -> bool {
    // 行情只读 + 前端静态；对话/因子等仍限流
    path.starts_with("/api/market")
        || path.starts_with("/api/research/cn-equity")
        || path.starts_with("/api/cn-equity")
        || matches!(classify(path), Upstream::Frontend)
}

/// 反向代理：限流 → 选上游 → 改写路径 → 转发（含 X-Trace-Id）。
async fn proxy(
    State(state): State<Arc<AppState>>,
    req: Request,
) -> Result<Response, (StatusCode, String)> {
    let peer = req
        .extensions()
        .get::<axum::extract::ConnectInfo<SocketAddr>>()
        .map(|c| c.0.ip())
        .unwrap_or_else(|| IpAddr::from([127, 0, 0, 1]));

    let path = req.uri().path().to_string();
    if !skip_rate_limit(&path) && !state.rate_limiter.is_allowed(peer) {
        return Err((StatusCode::TOO_MANY_REQUESTS, "rate limit exceeded".into()));
    }
    let query = req
        .uri()
        .query()
        .map(|q| format!("?{q}"))
        .unwrap_or_default();

    let upstream = classify(&path);
    let (upstream_base, forward_path) = match upstream {
        Upstream::Orchestrator => (state.orchestrator_url.as_str(), rewrite_path(upstream, &path)),
        Upstream::Research => (state.research_url.as_str(), rewrite_path(upstream, &path)),
        Upstream::MarketData => (state.market_data_url.as_str(), rewrite_path(upstream, &path)),
        Upstream::Frontend => (state.frontend_url.as_str(), rewrite_path(upstream, &path)),
    };

    let url = format!("{upstream_base}{forward_path}{query}");
    let method = req.method().clone();
    let headers = req.headers().clone();
    let body_bytes = axum::body::to_bytes(req.into_body(), 8 * 1024 * 1024)
        .await
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;

    let mut builder = state.http.request(
        reqwest::Method::from_bytes(method.as_str().as_bytes()).unwrap_or(reqwest::Method::GET),
        &url,
    );
    for (k, v) in headers.iter() {
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

    let status = StatusCode::from_u16(upstream.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
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
        .json()
        .with_env_filter(EnvFilter::from_default_env().add_directive("info".parse().unwrap()))
        .with_current_span(false)
        .with_span_list(false)
        .flatten_event(true)
        .init();

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(3000);
    let rpm: usize = std::env::var("RATE_LIMIT_PER_MINUTE")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(120);

    let _metrics = http_metrics::init("gateway");

    let state = Arc::new(AppState {
        http: reqwest::Client::new(),
        orchestrator_url: std::env::var("ORCHESTRATOR_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:8001".into()),
        research_url: std::env::var("RESEARCH_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:8002".into()),
        market_data_url: std::env::var("MARKET_DATA_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:3002".into()),
        frontend_url: std::env::var("FRONTEND_URL")
            .unwrap_or_else(|_| "http://127.0.0.1:3001".into()),
        rate_limiter: Arc::new(RateLimiter::new(Duration::from_secs(60), rpm)),
    });

    let app = Router::new()
        .route("/health", get(health))
        .route("/metrics", get(http_metrics::metrics_handler))
        .route(
            "/api/market/qdb/ws",
            get(ws_proxy::qdb_ws).post(ws_proxy::qdb_ws_http_fallback),
        )
        .route(
            "/api/market/exchanges/qdb/ws",
            get(ws_proxy::qdb_ws).post(ws_proxy::qdb_ws_http_fallback),
        )
        .route("/api/{*rest}", any(proxy))
        .route("/v1/{*rest}", any(proxy))
        .route("/", any(proxy))
        .route("/{*rest}", any(proxy))
        .layer(from_fn(http_metrics::metrics_middleware))
        .layer(from_fn(trace_middleware))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!(service = "gateway", %addr, "listening");
    let listener = tokio::net::TcpListener::bind(addr).await.expect("bind");
    axum::serve(
        listener,
        app.into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await
    .expect("serve");
}

#[cfg(test)]
mod tests {
    use super::{classify, rewrite_path, Upstream};

    #[test]
    fn rewrites_product_short_paths() {
        assert!(matches!(
            classify("/api/cn-equity/codes"),
            Upstream::Research
        ));
        assert_eq!(
            rewrite_path(Upstream::Research, "/api/cn-equity/codes"),
            "/cn-equity/codes"
        );
        assert_eq!(
            rewrite_path(Upstream::Research, "/api/backtests/run"),
            "/backtests/run"
        );
        assert_eq!(
            rewrite_path(Upstream::Research, "/api/research/factors/ic"),
            "/factors/ic"
        );
        assert_eq!(
            rewrite_path(Upstream::MarketData, "/api/market/quotes/x"),
            "/quotes/x"
        );
    }
}
