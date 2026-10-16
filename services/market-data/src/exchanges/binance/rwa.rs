//! 币安 Web3 Ondo 代币化美股公开行情（免 Key）。
//!
//! 上游文档：Binance Web3 tokenized securities（RWA）公开 bapi。
//! 挂载：`/exchanges/binance/rwa/*` · `/binance/rwa/*`

use axum::{
    extract::{Query, State},
    http::StatusCode,
    routing::get,
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

const UA: &str = "binance-web3/1.1 (Skill)";
const DEFAULT_BASE: &str = "https://www.binance.com";

#[derive(Clone)]
struct CacheEntry {
    value: Value,
    expires: Instant,
}

/// Ondo RWA HTTP 客户端（短 TTL 内存缓存）。
#[derive(Clone)]
pub struct RwaClient {
    http: reqwest::Client,
    base: String,
    cache: Arc<Mutex<HashMap<String, CacheEntry>>>,
}

impl RwaClient {
    pub fn from_env() -> Self {
        Self {
            http: reqwest::Client::builder()
                .user_agent(UA)
                .build()
                .unwrap_or_else(|_| reqwest::Client::new()),
            base: std::env::var("BINANCE_RWA_BASE_URL")
                .unwrap_or_else(|_| DEFAULT_BASE.into())
                .trim_end_matches('/')
                .to_string(),
            cache: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    fn cache_get(&self, key: &str) -> Option<Value> {
        let guard = self.cache.lock().ok()?;
        let e = guard.get(key)?;
        if e.expires > Instant::now() {
            Some(e.value.clone())
        } else {
            None
        }
    }

    fn cache_put(&self, key: String, value: Value, ttl: Duration) {
        if let Ok(mut guard) = self.cache.lock() {
            guard.insert(
                key,
                CacheEntry {
                    value,
                    expires: Instant::now() + ttl,
                },
            );
            if guard.len() > 256 {
                let now = Instant::now();
                guard.retain(|_, e| e.expires > now);
            }
        }
    }

    async fn get_bapi(
        &self,
        path: &str,
        query: &HashMap<String, String>,
        ttl: Duration,
    ) -> Result<Value, (StatusCode, String)> {
        let mut pairs: Vec<_> = query.iter().collect();
        pairs.sort_by(|a, b| a.0.cmp(b.0));
        let q = pairs
            .into_iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join("&");
        let key = format!("{path}?{q}");
        if let Some(hit) = self.cache_get(&key) {
            return Ok(hit);
        }

        let url = format!("{}{}", self.base, path);
        let mut req = self.http.get(&url).header("Accept-Encoding", "identity");
        if !query.is_empty() {
            req = req.query(query);
        }
        let res = req
            .send()
            .await
            .map_err(|e| (StatusCode::BAD_GATEWAY, format!("rwa connect: {e}")))?;
        let status = res.status();
        let body = res
            .text()
            .await
            .map_err(|e| (StatusCode::BAD_GATEWAY, format!("rwa body: {e}")))?;
        if !status.is_success() {
            return Err((
                StatusCode::BAD_GATEWAY,
                format!(
                    "rwa {status}: {}",
                    body.chars().take(240).collect::<String>()
                ),
            ));
        }
        let value: Value = serde_json::from_str(&body).map_err(|e| {
            (
                StatusCode::BAD_GATEWAY,
                format!("rwa json: {e}"),
            )
        })?;
        self.cache_put(key, value.clone(), ttl);
        Ok(value)
    }
}

pub fn router(client: Arc<RwaClient>) -> Router {
    Router::new()
        .route("/", get(catalog))
        .route("/stocks", get(stocks))
        .route("/market/status", get(market_status))
        .route("/asset/status", get(asset_status))
        .route("/meta", get(meta))
        .route("/dynamic", get(dynamic))
        .route("/klines", get(klines))
        .route("/quote", get(quote_by_ticker))
        .with_state(client)
}

async fn catalog() -> Json<Value> {
    Json(json!({
        "id": "binance-rwa",
        "name": "Binance Ondo Tokenized US Stocks (public)",
        "auth": "none",
        "upstream": "https://www.binance.com/bapi/defi/…/rwa/…",
        "docs": [
            "https://developers.binance.com/zh-CN/docs/introduction",
            "docs/2026-10-16-binance-market.md#代币化美股-ondo-rwa"
        ],
        "endpoints": [
            "GET .../rwa/stocks?type=1&preferChainId=56",
            "GET .../rwa/market/status",
            "GET .../rwa/asset/status?chainId=&contractAddress=",
            "GET .../rwa/meta?chainId=&contractAddress=",
            "GET .../rwa/dynamic?chainId=&contractAddress=",
            "GET .../rwa/klines?chainId=&contractAddress=&interval=&limit=",
            "GET .../rwa/quote?ticker=AAPL&preferChainId=56"
        ],
        "note": "代币化美股 ≠ 纽交所原生 feed；仅公开只读行情"
    }))
}

#[derive(Deserialize)]
pub struct StocksQuery {
    #[serde(default = "default_type")]
    pub r#type: u32,
    /// 优先链；同 ticker 多链时取该链（默认 BSC=56）
    #[serde(default = "default_prefer_chain", rename = "preferChainId")]
    pub prefer_chain_id: String,
    /// 若 true 则不去重，返回上游全量
    #[serde(default)]
    pub all: bool,
}

fn default_type() -> u32 {
    1
}
fn default_prefer_chain() -> String {
    "56".into()
}

async fn stocks(
    State(client): State<Arc<RwaClient>>,
    Query(q): Query<StocksQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let mut params = HashMap::new();
    params.insert("type".into(), q.r#type.to_string());
    let raw = client
        .get_bapi(
            "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/rwa/stock/detail/list/ai",
            &params,
            Duration::from_secs(60),
        )
        .await?;

    if q.all {
        return Ok(Json(raw));
    }

    let rows = raw
        .get("data")
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default();

    // ticker → 优先 prefer_chain，否则任意一条
    let mut best: HashMap<String, Value> = HashMap::new();
    for row in rows {
        let ticker = row
            .get("ticker")
            .and_then(|t| t.as_str())
            .unwrap_or("")
            .to_string();
        if ticker.is_empty() {
            continue;
        }
        let chain = row
            .get("chainId")
            .and_then(|c| c.as_str())
            .unwrap_or("");
        match best.get(&ticker) {
            None => {
                best.insert(ticker, row);
            }
            Some(prev) => {
                let prev_chain = prev.get("chainId").and_then(|c| c.as_str()).unwrap_or("");
                if chain == q.prefer_chain_id && prev_chain != q.prefer_chain_id {
                    best.insert(ticker, row);
                }
            }
        }
    }

    let mut list: Vec<Value> = best.into_values().collect();
    list.sort_by(|a, b| {
        let ta = a.get("ticker").and_then(|t| t.as_str()).unwrap_or("");
        let tb = b.get("ticker").and_then(|t| t.as_str()).unwrap_or("");
        ta.cmp(tb)
    });

    Ok(Json(json!({
        "code": raw.get("code").cloned().unwrap_or(json!("000000")),
        "success": true,
        "preferChainId": q.prefer_chain_id,
        "count": list.len(),
        "data": list
    })))
}

async fn market_status(
    State(client): State<Arc<RwaClient>>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let v = client
        .get_bapi(
            "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/rwa/market/status/ai",
            &HashMap::new(),
            Duration::from_secs(15),
        )
        .await?;
    Ok(Json(v))
}

#[derive(Deserialize)]
pub struct ChainContractQuery {
    #[serde(rename = "chainId")]
    pub chain_id: String,
    #[serde(rename = "contractAddress")]
    pub contract_address: String,
}

async fn asset_status(
    State(client): State<Arc<RwaClient>>,
    Query(q): Query<ChainContractQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let mut params = HashMap::new();
    params.insert("chainId".into(), q.chain_id);
    params.insert("contractAddress".into(), q.contract_address);
    let v = client
        .get_bapi(
            "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/rwa/asset/market/status/ai",
            &params,
            Duration::from_secs(10),
        )
        .await?;
    Ok(Json(v))
}

async fn meta(
    State(client): State<Arc<RwaClient>>,
    Query(q): Query<ChainContractQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let mut params = HashMap::new();
    params.insert("chainId".into(), q.chain_id);
    params.insert("contractAddress".into(), q.contract_address);
    let v = client
        .get_bapi(
            "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/rwa/meta/ai",
            &params,
            Duration::from_secs(300),
        )
        .await?;
    Ok(Json(v))
}

async fn dynamic(
    State(client): State<Arc<RwaClient>>,
    Query(q): Query<ChainContractQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let mut params = HashMap::new();
    params.insert("chainId".into(), q.chain_id);
    params.insert("contractAddress".into(), q.contract_address);
    let v = client
        .get_bapi(
            "/bapi/defi/v2/public/wallet-direct/buw/wallet/market/token/rwa/dynamic/ai",
            &params,
            Duration::from_secs(5),
        )
        .await?;
    Ok(Json(v))
}

#[derive(Deserialize)]
pub struct KlinesQuery {
    #[serde(rename = "chainId")]
    pub chain_id: String,
    #[serde(rename = "contractAddress")]
    pub contract_address: String,
    #[serde(default = "default_interval")]
    pub interval: String,
    #[serde(default = "default_kline_limit")]
    pub limit: u32,
}

fn default_interval() -> String {
    "1h".into()
}
fn default_kline_limit() -> u32 {
    200
}

async fn klines(
    State(client): State<Arc<RwaClient>>,
    Query(q): Query<KlinesQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let mut params = HashMap::new();
    params.insert("chainId".into(), q.chain_id);
    params.insert("contractAddress".into(), q.contract_address);
    params.insert("interval".into(), q.interval);
    params.insert("limit".into(), q.limit.min(300).to_string());
    let v = client
        .get_bapi(
            "/bapi/defi/v1/public/wallet-direct/buw/wallet/dex/market/token/kline/ai",
            &params,
            Duration::from_secs(20),
        )
        .await?;
    Ok(Json(v))
}

#[derive(Deserialize)]
pub struct QuoteQuery {
    pub ticker: String,
    #[serde(default = "default_prefer_chain", rename = "preferChainId")]
    pub prefer_chain_id: String,
}

/// 按底层美股 ticker 解析合约并返回 dynamic（含 token/stock 信息）。
async fn quote_by_ticker(
    State(client): State<Arc<RwaClient>>,
    Query(q): Query<QuoteQuery>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let ticker = q.ticker.trim().to_uppercase();
    let mut params = HashMap::new();
    params.insert("type".into(), "1".into());
    let raw = client
        .get_bapi(
            "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/rwa/stock/detail/list/ai",
            &params,
            Duration::from_secs(60),
        )
        .await?;

    let rows = raw
        .get("data")
        .and_then(|d| d.as_array())
        .cloned()
        .unwrap_or_default();
    let matches: Vec<_> = rows
        .into_iter()
        .filter(|r| {
            r.get("ticker")
                .and_then(|t| t.as_str())
                .map(|t| t.eq_ignore_ascii_case(&ticker))
                .unwrap_or(false)
        })
        .collect();
    if matches.is_empty() {
        return Err((StatusCode::NOT_FOUND, format!("ticker not found: {ticker}")));
    }
    let pick = matches
        .iter()
        .find(|r| {
            r.get("chainId").and_then(|c| c.as_str()) == Some(q.prefer_chain_id.as_str())
        })
        .or_else(|| matches.first())
        .cloned()
        .unwrap();

    let chain_id = pick
        .get("chainId")
        .and_then(|c| c.as_str())
        .unwrap_or("56")
        .to_string();
    let contract = pick
        .get("contractAddress")
        .and_then(|c| c.as_str())
        .unwrap_or("")
        .to_string();
    if contract.is_empty() {
        return Err((StatusCode::BAD_GATEWAY, "missing contractAddress".into()));
    }

    let mut dparams = HashMap::new();
    dparams.insert("chainId".into(), chain_id.clone());
    dparams.insert("contractAddress".into(), contract.clone());
    let dyn_raw = client
        .get_bapi(
            "/bapi/defi/v2/public/wallet-direct/buw/wallet/market/token/rwa/dynamic/ai",
            &dparams,
            Duration::from_secs(5),
        )
        .await?;

    Ok(Json(json!({
        "ticker": ticker,
        "token": pick,
        "chainId": chain_id,
        "contractAddress": contract,
        "dynamic": dyn_raw.get("data").cloned().unwrap_or(Value::Null),
        "upstreamCode": dyn_raw.get("code").cloned().unwrap_or(json!("000000")),
    })))
}
