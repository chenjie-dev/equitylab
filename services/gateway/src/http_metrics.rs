//! HTTP Prometheus 指标：请求计数 / 延迟（路径粗分组，避免高基数）。

use axum::{
    body::Body,
    extract::Request,
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
};
use metrics::{counter, histogram};
use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};
use std::sync::OnceLock;
use std::time::Instant;

static HANDLE: OnceLock<PrometheusHandle> = OnceLock::new();

pub fn init(service: &str) -> PrometheusHandle {
    HANDLE
        .get_or_init(|| {
            PrometheusBuilder::new()
                .add_global_label("service", service)
                .install_recorder()
                .expect("prometheus recorder")
        })
        .clone()
}

pub async fn metrics_handler() -> impl IntoResponse {
    let body = HANDLE
        .get()
        .map(|h| h.render())
        .unwrap_or_else(|| "# metrics recorder not installed\n".into());
    (
        StatusCode::OK,
        [("content-type", "text/plain; version=0.0.4; charset=utf-8")],
        body,
    )
}

/// 粗分路径：固定前缀或前两段，避免 `/cn-equity/klines/{code}` 爆炸。
pub fn path_group(path: &str) -> String {
    let path = path.split('?').next().unwrap_or(path);
    if path == "/health" || path == "/metrics" {
        return path.to_string();
    }
    let prefixes = [
        "/api/cn-equity/klines",
        "/api/cn-equity/quotes",
        "/api/cn-equity/codes",
        "/api/cn-equity/five",
        "/api/cn-equity/intraday",
        "/api/cn-equity",
        "/api/research/cn-equity/klines",
        "/api/research/cn-equity/quotes",
        "/api/research/cn-equity/codes",
        "/api/research/cn-equity/five",
        "/api/research/cn-equity/intraday",
        "/api/research/cn-equity",
        "/api/research/rag",
        "/api/research/factors",
        "/api/research/backtests",
        "/api/backtests",
        "/api/research",
        "/api/market/qdb/ws",
        "/api/market",
        "/api/chat",
        "/v1",
    ];
    for p in prefixes {
        if path == p || path.starts_with(&format!("{p}/")) {
            return p.to_string();
        }
    }
    let parts: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
    match parts.len() {
        0 => "/".into(),
        1 => format!("/{}", parts[0]),
        _ => format!("/{}/{}", parts[0], parts[1]),
    }
}

pub async fn metrics_middleware(req: Request<Body>, next: Next) -> Response {
    let method = req.method().as_str().to_string();
    let group = path_group(req.uri().path());
    if group == "/metrics" {
        return next.run(req).await;
    }
    let start = Instant::now();
    let response = next.run(req).await;
    let status = response.status().as_u16().to_string();
    let elapsed = start.elapsed().as_secs_f64();
    counter!(
        "http_requests_total",
        "method" => method.clone(),
        "path_group" => group.clone(),
        "status" => status
    )
    .increment(1);
    histogram!(
        "http_request_duration_seconds",
        "method" => method,
        "path_group" => group
    )
    .record(elapsed);
    response
}
