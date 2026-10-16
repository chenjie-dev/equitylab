//! HTTP handlers：健康检查、报价、K 线、搜索。
//!
//! 报价路径优先读缓存；未命中再打 Provider，并写回 TTL=3s（立项约定）。

use crate::providers::ProviderError;
use crate::AppState;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

/// 健康检查响应体，字段与网关 / 编排层保持一致便于统一探活。
#[derive(Serialize)]
pub struct HealthBody {
    status: &'static str,
    service: &'static str,
    ts: String,
}

/// `GET /health`
pub async fn health() -> Json<HealthBody> {
    Json(HealthBody {
        status: "UP",
        service: "market-data",
        ts: Utc::now().to_rfc3339(),
    })
}

/// `GET /quotes/{symbol}` — 实时快照；缓存命中则不打上游。
pub async fn get_quote(
    State(state): State<Arc<AppState>>,
    Path(symbol): Path<String>,
) -> Result<Json<crate::providers::Quote>, (StatusCode, String)> {
    if let Some(quote) = state.cache.get(&symbol).await {
        return Ok(Json(quote));
    }
    let quote = state
        .provider
        .get_quote(&symbol)
        .await
        .map_err(map_err)?;
    // 立项：实时快照 Redis TTL 3 秒，避免每次 MCP/FC 都打上游。
    state.cache.set(&symbol, &quote, crate::cache::QUOTE_TTL_SECS).await;
    Ok(Json(quote))
}

/// K 线查询参数；缺省对应日线、60 根、不复权。
#[derive(Deserialize)]
pub struct BarsQuery {
    #[serde(default = "default_period")]
    period: String,
    #[serde(default = "default_count")]
    count: usize,
    #[serde(default = "default_adjust")]
    adjust: String,
}

fn default_period() -> String {
    "1d".into()
}
fn default_count() -> usize {
    60
}
fn default_adjust() -> String {
    "none".into()
}

/// `GET /bars/{symbol}` — 历史 K 线（MVP 不经缓存；落 PG 后续）。
pub async fn get_bars(
    State(state): State<Arc<AppState>>,
    Path(symbol): Path<String>,
    Query(q): Query<BarsQuery>,
) -> Result<Json<Vec<crate::providers::Bar>>, (StatusCode, String)> {
    let bars = state
        .provider
        .get_bars(&symbol, &q.period, q.count, &q.adjust)
        .await
        .map_err(map_err)?;
    Ok(Json(bars))
}

#[derive(Deserialize)]
pub struct SearchQuery {
    #[serde(default)]
    q: String,
}

/// `GET /search?q=` — 标的模糊搜索。
pub async fn search(
    State(state): State<Arc<AppState>>,
    Query(q): Query<SearchQuery>,
) -> Result<Json<Vec<crate::providers::Quote>>, (StatusCode, String)> {
    let items = state.provider.search(&q.q).await.map_err(map_err)?;
    Ok(Json(items))
}

/// 将 Provider 错误映射为 HTTP 状态：未找到 → 404，上游失败 → 502。
fn map_err(e: ProviderError) -> (StatusCode, String) {
    match e {
        ProviderError::NotFound(msg) => (StatusCode::NOT_FOUND, msg),
        ProviderError::Upstream(msg) => (StatusCode::BAD_GATEWAY, msg),
    }
}
