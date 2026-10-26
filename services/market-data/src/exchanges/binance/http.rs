//! 币安公开 REST HTTP 处理器（模块内 state = [`super::Client`]）。

use super::client::{normalize_symbol, Client};
use crate::providers::ProviderError;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use futures_util::future::join_all;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{collections::HashMap, sync::Arc};

fn map_err(e: ProviderError) -> (StatusCode, String) {
    match e {
        ProviderError::NotFound(msg) => (StatusCode::NOT_FOUND, msg),
        ProviderError::Upstream(msg) => (StatusCode::BAD_GATEWAY, msg),
    }
}

pub async fn ping() -> Json<Value> {
    // 不回源币安；存活由本服务 + qdb 读路径保证
    Json(json!({}))
}

pub async fn server_time() -> Json<Value> {
    use std::time::{SystemTime, UNIX_EPOCH};
    let ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0);
    Json(json!({ "serverTime": ms, "source": "local" }))
}

pub async fn exchange_info(
    State(client): State<Arc<Client>>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let v = client.exchange_info().await.map_err(map_err)?;
    Ok(Json(v))
}

pub async fn proxy_v3(
    Path(path): Path<String>,
    Query(_query): Query<HashMap<String, String>>,
) -> Result<Json<Value>, (StatusCode, String)> {
    Err((
        StatusCode::FORBIDDEN,
        format!(
            "qdb-only: refusing upstream proxy /v3/{path}; use typed endpoints that read qdb"
        ),
    ))
}

#[derive(Deserialize)]
pub struct DepthQuery {
    pub symbol: String,
    #[serde(default = "default_depth")]
    pub limit: u32,
}

fn default_depth() -> u32 {
    20
}

#[derive(Deserialize)]
pub struct TradesQuery {
    pub symbol: String,
    #[serde(default = "default_trades")]
    pub limit: u32,
}

fn default_trades() -> u32 {
    50
}

#[derive(Deserialize)]
pub struct KlinesQuery {
    pub symbol: String,
    #[serde(default = "default_interval")]
    pub interval: String,
    #[serde(default = "default_klines")]
    pub limit: usize,
    /// 币安同名：只要 openTime ≤ endTime 的最后 limit 根（向前翻历史）
    #[serde(default, rename = "endTime")]
    pub end_time: Option<u64>,
}

fn default_interval() -> String {
    "1h".into()
}
fn default_klines() -> usize {
    200
}

pub async fn ticker_price(
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let symbols = ticker_symbols(&q);
    let futs = symbols.into_iter().map(|symbol| async move {
        crate::qdb_read::doc(&format!("binance:ticker:{symbol}"))
            .await
            .map(|row| {
                json!({
                    "symbol": symbol,
                    "price": row.get("lastPrice").cloned().unwrap_or(json!("0")),
                })
            })
    });
    let rows: Vec<Value> = join_all(futs).await.into_iter().flatten().collect();
    if q.contains_key("symbol") {
        return Ok(Json(rows.into_iter().next().unwrap_or(Value::Null)));
    }
    Ok(Json(Value::Array(rows)))
}

pub async fn book_ticker(
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let symbol = q.get("symbol").map(|s| normalize_symbol(s)).unwrap_or_default();
    let depth = crate::qdb_read::doc(&format!("binance:depth:{symbol}"))
        .await
        .unwrap_or_else(|| json!({"bids": [], "asks": []}));
    let bid = depth.get("bids").and_then(|v| v.as_array()).and_then(|a| a.first());
    let ask = depth.get("asks").and_then(|v| v.as_array()).and_then(|a| a.first());
    Ok(Json(json!({
        "symbol": symbol,
        "bidPrice": bid.and_then(|r| r.get(0)).cloned().unwrap_or(json!("0")),
        "bidQty": bid.and_then(|r| r.get(1)).cloned().unwrap_or(json!("0")),
        "askPrice": ask.and_then(|r| r.get(0)).cloned().unwrap_or(json!("0")),
        "askQty": ask.and_then(|r| r.get(1)).cloned().unwrap_or(json!("0")),
    })))
}

pub async fn avg_price(
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let symbol = q.get("symbol").map(|s| normalize_symbol(s)).unwrap_or_default();
    let row = crate::qdb_read::doc(&format!("binance:ticker:{symbol}")).await;
    Ok(Json(json!({
        "mins": 1440,
        "price": row.as_ref().and_then(|r| r.get("weightedAvgPrice")).cloned().unwrap_or(json!("0")),
    })))
}

pub async fn ui_klines(Query(q): Query<KlinesQuery>) -> Result<Json<Value>, (StatusCode, String)> {
    klines(Query(q)).await
}

pub async fn agg_trades(Query(q): Query<TradesQuery>) -> Result<Json<Value>, (StatusCode, String)> {
    trades(Query(q)).await
}

pub async fn ticker_24hr(
    Query(q): Query<HashMap<String, String>>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let symbols = ticker_symbols(&q);
    // 多标的 docs 并行读，避免 watchlist 串行拉长列表首屏
    let futs = symbols.into_iter().map(|symbol| async move {
        crate::qdb_read::doc(&format!("binance:ticker:{symbol}")).await
    });
    let rows: Vec<Value> = join_all(futs).await.into_iter().flatten().collect();
    if q.contains_key("symbol") {
        return Ok(Json(rows.into_iter().next().unwrap_or(Value::Null)));
    }
    Ok(Json(Value::Array(rows)))
}

fn ticker_symbols(q: &HashMap<String, String>) -> Vec<String> {
    if let Some(one) = q.get("symbol") {
        return vec![normalize_symbol(one)];
    }
    let Some(raw) = q.get("symbols") else {
        return Vec::new();
    };
    serde_json::from_str::<Vec<String>>(raw)
        .unwrap_or_default()
        .into_iter()
        .map(|s| normalize_symbol(&s))
        .collect()
}

pub async fn depth(
    Query(q): Query<DepthQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let symbol = normalize_symbol(&q.symbol);
    let v = crate::qdb_read::doc(&format!("binance:depth:{symbol}"))
        .await
        .unwrap_or_else(|| json!({"lastUpdateId": 0, "bids": [], "asks": []}));
    Ok(Json(v))
}

pub async fn trades(Query(q): Query<TradesQuery>) -> Result<Json<Value>, (StatusCode, String)> {
    let symbol = normalize_symbol(&q.symbol);
    let v = crate::qdb_read::doc(&format!("binance:trades:{symbol}"))
        .await
        .unwrap_or_else(|| json!([]));
    Ok(Json(v))
}

pub async fn klines(Query(q): Query<KlinesQuery>) -> Result<Json<Value>, (StatusCode, String)> {
    let symbol = normalize_symbol(&q.symbol);
    let limit = q.limit.clamp(1, 1500);
    let rows =
        crate::qdb_read::binance_klines(&symbol, &q.interval, limit, q.end_time).await;
    Ok(Json(Value::Array(rows)))
}

pub async fn catalog() -> Json<Value> {
    Json(json!({
        "id": super::ID,
        "provider": "binance-spot-public",
        "auth": "none",
        "mounts": ["/exchanges/binance", "/binance"],
        "rest": [
            "GET .../ping",
            "GET .../time",
            "GET .../exchangeInfo",
            "GET .../ticker/24hr?symbol=",
            "GET .../ticker/price?symbol=",
            "GET .../ticker/bookTicker?symbol=",
            "GET .../avgPrice?symbol=",
            "GET .../depth?symbol=&limit=",
            "GET .../trades?symbol=&limit=",
            "GET .../aggTrades?symbol=&limit=",
            "GET .../klines?symbol=&interval=&limit=",
            "GET .../uiKlines?symbol=&interval=&limit=",
            "GET .../v3/{*path}"
        ],
        "websocket": [
            "WS /qdb/ws — SELECT … SUBSCRIBE（唯一订阅读）",
            "WS .../ws — refused (qdb-only; no upstream Binance proxy)"
        ],
        "unified": [
            "GET /quotes/{symbol} when MARKET_PROVIDER=binance",
            "GET /bars/{symbol}?period=1h&count=100",
            "GET /search?q=BTC"
        ],
        "rwa": [
            "GET .../rwa/stocks",
            "GET .../rwa/board?tickers=",
            "GET .../rwa/market/status",
            "GET .../rwa/dynamic?chainId=&contractAddress=",
            "GET .../rwa/klines?chainId=&contractAddress=&interval=",
            "GET .../rwa/quote?ticker=AAPL"
        ],
        "symbol": "BTCUSDT (also btc/usdt); RWA ticker e.g. AAPL",
        "note": "读路径只读 qdb；/v3/{*} 与 /ws 上游代理已拒绝；订阅读用 /qdb/ws"
    }))
}
