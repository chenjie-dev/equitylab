//! 币安公开 REST HTTP 处理器（模块内 state = [`super::Client`]）。

use super::client::{normalize_symbol, Client};
use crate::providers::ProviderError;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{collections::HashMap, sync::Arc};

fn map_err(e: ProviderError) -> (StatusCode, String) {
    match e {
        ProviderError::NotFound(msg) => (StatusCode::NOT_FOUND, msg),
        ProviderError::Upstream(msg) => (StatusCode::BAD_GATEWAY, msg),
    }
}

pub async fn ping(State(client): State<Arc<Client>>) -> Result<Json<Value>, (StatusCode, String)> {
    let v = client
        .get_v3("ping", &HashMap::new())
        .await
        .map_err(map_err)?;
    Ok(Json(v))
}

pub async fn server_time(
    State(client): State<Arc<Client>>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let v = client
        .get_v3("time", &HashMap::new())
        .await
        .map_err(map_err)?;
    Ok(Json(v))
}

pub async fn exchange_info(
    State(client): State<Arc<Client>>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let v = client.exchange_info().await.map_err(map_err)?;
    Ok(Json(v))
}

pub async fn proxy_v3(
    State(client): State<Arc<Client>>,
    Path(path): Path<String>,
    Query(query): Query<HashMap<String, String>>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let lower = path.to_lowercase();
    for deny in ["order", "account", "sapi", "wapi", "userdata", "margin", "listenkey"] {
        if lower.contains(deny) {
            return Err((
                StatusCode::FORBIDDEN,
                format!("refusing non-public path segment: {deny}"),
            ));
        }
    }
    let v = client.get_v3(&path, &query).await.map_err(map_err)?;
    Ok(Json(v))
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
}

fn default_interval() -> String {
    "1h".into()
}
fn default_klines() -> usize {
    100
}

macro_rules! binance_get {
    ($name:ident, $path:expr) => {
        pub async fn $name(
            State(client): State<Arc<Client>>,
            Query(q): Query<HashMap<String, String>>,
        ) -> Result<Json<Value>, (StatusCode, String)> {
            let v = client.get_v3($path, &q).await.map_err(map_err)?;
            Ok(Json(v))
        }
    };
}

binance_get!(ticker_24hr, "ticker/24hr");
binance_get!(ticker_price, "ticker/price");
binance_get!(book_ticker, "ticker/bookTicker");
binance_get!(avg_price, "avgPrice");
binance_get!(ui_klines, "uiKlines");
binance_get!(agg_trades, "aggTrades");

pub async fn depth(
    State(client): State<Arc<Client>>,
    Query(q): Query<DepthQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let mut params = HashMap::new();
    params.insert("symbol".into(), normalize_symbol(&q.symbol));
    params.insert("limit".into(), q.limit.min(5000).to_string());
    let v = client.get_v3("depth", &params).await.map_err(map_err)?;
    Ok(Json(v))
}

pub async fn trades(
    State(client): State<Arc<Client>>,
    Query(q): Query<TradesQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let mut params = HashMap::new();
    params.insert("symbol".into(), normalize_symbol(&q.symbol));
    params.insert("limit".into(), q.limit.min(1000).to_string());
    let v = client.get_v3("trades", &params).await.map_err(map_err)?;
    Ok(Json(v))
}

pub async fn klines(
    State(client): State<Arc<Client>>,
    Query(q): Query<KlinesQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let rows = client
        .klines(&q.symbol, &q.interval, q.limit)
        .await
        .map_err(map_err)?;
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
            "WS .../ws?streams=btcusdt@trade/btcusdt@ticker",
            "WS .../ws?stream=btcusdt@kline_1m"
        ],
        "unified": [
            "GET /quotes/{symbol} when MARKET_PROVIDER=binance",
            "GET /bars/{symbol}?period=1h&count=100",
            "GET /search?q=BTC"
        ],
        "rwa": [
            "GET .../rwa/stocks",
            "GET .../rwa/market/status",
            "GET .../rwa/dynamic?chainId=&contractAddress=",
            "GET .../rwa/klines?chainId=&contractAddress=&interval=",
            "GET .../rwa/quote?ticker=AAPL"
        ],
        "symbol": "BTCUSDT (also btc/usdt); RWA ticker e.g. AAPL",
        "note": "WebSocket 请直连 market-data 端口（网关 HTTP 反代不升级 WS）；RWA 为 Ondo 代币化美股公开行情"
    }))
}
