//! 币安 Web3 Ondo 代币化美股公开行情（免 Key）。
//!
//! 上游文档：Binance Web3 tokenized securities（RWA）公开 bapi。
//! 挂载：`/exchanges/binance/rwa/*` · `/binance/rwa/*`

use axum::{
    extract::Query,
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

#[allow(dead_code)]
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
        .route("/board", get(board))
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
            "GET .../rwa/board",
            "GET .../rwa/market/status",
            "GET .../rwa/asset/status?chainId=&contractAddress=",
            "GET .../rwa/meta?chainId=&contractAddress=",
            "GET .../rwa/dynamic?chainId=&contractAddress=",
            "GET .../rwa/klines?chainId=&contractAddress=&interval=&limit=",
            "GET .../rwa/quote?ticker=AAPL&preferChainId=56"
        ],
        "note": "代币化美股 ≠ 纽交所原生 feed；列表 board / K 线 rwa:kline:* 由 collector 全量持续写"
    }))
}

/// collector 聚合的全市场轻量报价（`rwa:board`），供列表一次读完。
async fn board() -> Result<Json<Value>, (StatusCode, String)> {
    let v = crate::qdb_read::doc("rwa:board").await.unwrap_or_else(|| {
        json!({"updatedAt": 0, "count": 0, "data": {}})
    });
    Ok(Json(v))
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

async fn stocks(Query(q): Query<StocksQuery>) -> Result<Json<Value>, (StatusCode, String)> {
    let raw = crate::qdb_read::doc("rwa:stocks").await.unwrap_or_else(|| {
        json!({"code": "000000", "success": true, "count": 0, "data": []})
    });

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

async fn market_status() -> Result<Json<Value>, (StatusCode, String)> {
    let v = crate::qdb_read::doc("rwa:status")
        .await
        .unwrap_or_else(|| json!({"data": null}));
    Ok(Json(v))
}

#[derive(Deserialize)]
pub struct ChainContractQuery {
    #[serde(rename = "chainId")]
    pub chain_id: String,
    #[serde(rename = "contractAddress")]
    pub contract_address: String,
}

async fn asset_status(Query(q): Query<ChainContractQuery>) -> Result<Json<Value>, (StatusCode, String)> {
    let key = format!("rwa:status:{}:{}", q.chain_id, q.contract_address);
    let v = crate::qdb_read::doc(&key)
        .await
        .unwrap_or_else(|| json!({"data": null}));
    Ok(Json(v))
}

async fn meta(Query(q): Query<ChainContractQuery>) -> Result<Json<Value>, (StatusCode, String)> {
    let key = format!("rwa:meta:{}:{}", q.chain_id, q.contract_address);
    let v = crate::qdb_read::doc(&key)
        .await
        .unwrap_or_else(|| json!({"data": null}));
    Ok(Json(v))
}

async fn dynamic(Query(q): Query<ChainContractQuery>) -> Result<Json<Value>, (StatusCode, String)> {
    let key = format!("rwa:dynamic:{}:{}", q.chain_id, q.contract_address);
    let v = crate::qdb_read::doc(&key)
        .await
        .unwrap_or_else(|| json!({"data": null}));
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

async fn klines(Query(q): Query<KlinesQuery>) -> Result<Json<Value>, (StatusCode, String)> {
    let limit = q.limit.min(300) as usize;
    let ticker = ticker_for_contract(&q.chain_id, &q.contract_address)
        .await
        .unwrap_or_default();
    // collector 全市场写入的原始 K 线 doc；优先于成交折叠
    if !ticker.is_empty() {
        let key = format!("rwa:kline:{ticker}:{}", q.interval);
        if let Some(doc) = crate::qdb_read::doc(&key).await {
            if let Some(infos) = doc
                .pointer("/data/klineInfos")
                .and_then(|v| v.as_array())
            {
                let start = infos.len().saturating_sub(limit);
                return Ok(Json(json!({
                    "data": { "klineInfos": infos[start..].to_vec() }
                })));
            }
        }
    }
    let infos = crate::qdb_read::rwa_klines(&ticker, &q.interval, limit).await;
    Ok(Json(json!({"data": {"klineInfos": infos}})))
}

async fn ticker_for_contract(chain: &str, contract: &str) -> Option<String> {
    let doc = crate::qdb_read::doc("rwa:stocks").await?;
    for row in doc.get("data")?.as_array()? {
        let same_chain = row.get("chainId").and_then(|v| v.as_str()) == Some(chain);
        let same_contract = row.get("contractAddress").and_then(|v| v.as_str()) == Some(contract);
        if same_chain && same_contract {
            return row.get("ticker").and_then(|v| v.as_str()).map(|s| s.to_uppercase());
        }
    }
    None
}

#[derive(Deserialize)]
pub struct QuoteQuery {
    pub ticker: String,
    #[serde(default = "default_prefer_chain", rename = "preferChainId")]
    pub prefer_chain_id: String,
}

/// 按底层美股 ticker 解析合约并返回 dynamic（含 token/stock 信息）。
/// 优先 `rwa:quote:{TICKER}`；缺失时从 `rwa:stocks` + `rwa:dynamic` 拼装（collector 超时未写入时避免硬 404）。
async fn quote_by_ticker(Query(q): Query<QuoteQuery>) -> Result<Json<Value>, (StatusCode, String)> {
    let ticker = q.ticker.trim().to_uppercase();
    if let Some(v) = crate::qdb_read::doc(&format!("rwa:quote:{ticker}")).await {
        return Ok(Json(v));
    }
    let token = token_from_stocks(&ticker, &q.prefer_chain_id)
        .await
        .ok_or_else(|| (StatusCode::NOT_FOUND, format!("ticker not found: {ticker}")))?;
    let chain = token
        .get("chainId")
        .and_then(|v| v.as_str())
        .unwrap_or(&q.prefer_chain_id)
        .to_string();
    let contract = token
        .get("contractAddress")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let dynamic = if !contract.is_empty() {
        crate::qdb_read::doc(&format!("rwa:dynamic:{chain}:{contract}"))
            .await
            .and_then(|raw| raw.get("data").cloned())
    } else {
        None
    };
    Ok(Json(json!({
        "ticker": ticker,
        "token": token,
        "chainId": chain,
        "contractAddress": contract,
        "dynamic": dynamic,
    })))
}

async fn token_from_stocks(ticker: &str, prefer_chain: &str) -> Option<Value> {
    let doc = crate::qdb_read::doc("rwa:stocks").await?;
    let rows = doc.get("data")?.as_array()?;
    let mut fallback: Option<Value> = None;
    for row in rows {
        let t = row
            .get("ticker")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_uppercase();
        if t != ticker {
            continue;
        }
        let chain = row.get("chainId").and_then(|v| v.as_str()).unwrap_or("");
        if chain == prefer_chain {
            return Some(row.clone());
        }
        if fallback.is_none() {
            fallback = Some(row.clone());
        }
    }
    fallback
}
