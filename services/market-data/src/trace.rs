//! `X-Trace-Id` 中间件与 JSON access log（与网关约定一致）。

use axum::{
    body::Body,
    extract::Request,
    http::{HeaderName, HeaderValue},
    middleware::Next,
    response::Response,
};
use std::time::Instant;

pub const TRACE_HEADER: &str = "x-trace-id";

fn resolve_trace_id(req: &Request) -> String {
    req.headers()
        .get(TRACE_HEADER)
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(ToOwned::to_owned)
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string())
}

pub async fn trace_middleware(mut req: Request<Body>, next: Next) -> Response {
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
        service = "market-data",
        method = %method,
        path = %path,
        status = res.status().as_u16(),
        latencyMs = started.elapsed().as_millis() as u64,
        "request"
    );
    res
}
