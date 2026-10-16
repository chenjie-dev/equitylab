//! 币安公开 REST 客户端（内存短 TTL 缓存，避免前端轮询打爆限流）。

use crate::providers::ProviderError;
use serde::Deserialize;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[derive(Clone)]
struct CacheEntry {
    value: Value,
    expires: Instant,
}

/// 币安 REST/WS 基址与 HTTP 客户端；`Clone` 廉价，亦可包在 `Arc` 中共享。
#[derive(Clone)]
pub struct Client {
    http: reqwest::Client,
    rest_base: String,
    pub ws_base: String,
    cache: Arc<Mutex<HashMap<String, CacheEntry>>>,
}

impl Client {
    pub fn from_env() -> Self {
        Self {
            http: reqwest::Client::builder()
                .user_agent("equitylab-market-data/binance")
                .build()
                .unwrap_or_else(|_| reqwest::Client::new()),
            rest_base: std::env::var("BINANCE_REST_URL")
                .unwrap_or_else(|_| "https://data-api.binance.vision".into())
                .trim_end_matches('/')
                .to_string(),
            ws_base: std::env::var("BINANCE_WS_URL")
                .unwrap_or_else(|_| "wss://data-stream.binance.vision".into())
                .trim_end_matches('/')
                .to_string(),
            cache: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    fn cache_key(path: &str, query: &HashMap<String, String>) -> String {
        let mut pairs: Vec<_> = query.iter().collect();
        pairs.sort_by(|a, b| a.0.cmp(b.0));
        let q = pairs
            .into_iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect::<Vec<_>>()
            .join("&");
        format!("{path}?{q}")
    }

    fn cache_ttl(path: &str) -> Duration {
        match path {
            "ticker/24hr" | "ticker/price" | "ticker/bookTicker" => Duration::from_secs(3),
            "depth" | "trades" | "aggTrades" => Duration::from_secs(2),
            "klines" | "uiKlines" => Duration::from_secs(15),
            "exchangeInfo" => Duration::from_secs(60),
            _ => Duration::from_secs(3),
        }
    }

    fn cache_get(&self, key: &str) -> Option<Value> {
        let guard = self.cache.lock().ok()?;
        let entry = guard.get(key)?;
        if entry.expires > Instant::now() {
            Some(entry.value.clone())
        } else {
            None
        }
    }

    /// 过期但仍保留的条目（限流时兜底）。
    fn cache_stale(&self, key: &str) -> Option<Value> {
        let guard = self.cache.lock().ok()?;
        guard.get(key).map(|e| e.value.clone())
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
            // 粗略限大小，避免无限制增长
            if guard.len() > 512 {
                let now = Instant::now();
                guard.retain(|_, e| e.expires > now);
            }
        }
    }

    pub async fn get_v3(
        &self,
        path: &str,
        query: &HashMap<String, String>,
    ) -> Result<Value, ProviderError> {
        let path = path.trim_start_matches('/');
        let key = Self::cache_key(path, query);
        if let Some(hit) = self.cache_get(&key) {
            return Ok(hit);
        }

        let url = format!("{}/api/v3/{}", self.rest_base, path);
        let mut req = self.http.get(&url);
        if !query.is_empty() {
            req = req.query(query);
        }
        let res = req
            .send()
            .await
            .map_err(|e| ProviderError::Upstream(format!("binance connect: {e}")))?;
        let status = res.status();
        let body = res
            .text()
            .await
            .map_err(|e| ProviderError::Upstream(format!("binance body: {e}")))?;

        if status.as_u16() == 418 || status.as_u16() == 429 {
            if let Some(stale) = self.cache_stale(&key) {
                tracing::warn!(path, %status, "binance rate-limited; serving stale cache");
                return Ok(stale);
            }
            return Err(ProviderError::Upstream(format!(
                "binance {status}: {}",
                body.chars().take(240).collect::<String>()
            )));
        }

        if !status.is_success() {
            return Err(ProviderError::Upstream(format!(
                "binance {status}: {}",
                body.chars().take(240).collect::<String>()
            )));
        }
        let value: Value = serde_json::from_str(&body)
            .map_err(|e| ProviderError::Upstream(format!("binance json: {e}")))?;
        self.cache_put(key, value.clone(), Self::cache_ttl(path));
        Ok(value)
    }

    pub async fn ticker_24hr(&self, symbol: &str) -> Result<Ticker24hr, ProviderError> {
        let mut q = HashMap::new();
        q.insert("symbol".into(), normalize_symbol(symbol));
        let v = self.get_v3("ticker/24hr", &q).await?;
        serde_json::from_value(v)
            .map_err(|e| ProviderError::Upstream(format!("ticker parse: {e}")))
    }

    pub async fn klines(
        &self,
        symbol: &str,
        interval: &str,
        limit: usize,
    ) -> Result<Vec<Value>, ProviderError> {
        let mut q = HashMap::new();
        q.insert("symbol".into(), normalize_symbol(symbol));
        q.insert("interval".into(), map_interval(interval));
        q.insert("limit".into(), limit.clamp(1, 1000).to_string());
        let v = self.get_v3("klines", &q).await?;
        v.as_array()
            .cloned()
            .ok_or_else(|| ProviderError::Upstream("klines not array".into()))
    }

    pub async fn exchange_info(&self) -> Result<Value, ProviderError> {
        self.get_v3("exchangeInfo", &HashMap::new()).await
    }
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Ticker24hr {
    pub symbol: String,
    #[serde(default)]
    pub last_price: String,
    #[serde(default)]
    pub open_price: String,
    #[serde(default)]
    pub high_price: String,
    #[serde(default)]
    pub low_price: String,
    #[serde(default)]
    pub volume: String,
    #[serde(default)]
    pub quote_volume: String,
    #[serde(default)]
    pub price_change_percent: String,
    #[serde(default)]
    pub close_time: i64,
}

/// `BTCUSDT` / `btc/usdt` / `BTC-USDT` → `BTCUSDT`
pub fn normalize_symbol(raw: &str) -> String {
    raw.trim()
        .to_uppercase()
        .replace('/', "")
        .replace('-', "")
        .replace('_', "")
        .replace('.', "")
}

pub fn map_interval(period: &str) -> String {
    let p = period.trim();
    if p == "1M" {
        return "1M".into();
    }
    match p.to_lowercase().as_str() {
        "day" | "d" | "daily" => "1d".into(),
        "hour" | "h" => "1h".into(),
        "week" | "w" => "1w".into(),
        "month" | "1mth" => "1M".into(),
        "1m" | "3m" | "5m" | "15m" | "30m" | "1h" | "2h" | "4h" | "6h" | "8h" | "12h" | "1d"
        | "3d" | "1w" => p.to_lowercase(),
        other => other.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_variants() {
        assert_eq!(normalize_symbol("btc/usdt"), "BTCUSDT");
        assert_eq!(normalize_symbol("BTC-USDT"), "BTCUSDT");
    }
}
