//! qdb HTTP 客户端。读路径给 market-data / research；写给 collector 纪律使用。
//! 权威契约：同级仓 `qdb/docs/manual/`。

use serde_json::{json, Value};
use thiserror::Error;

pub const PRICE_SCALE: i64 = 10_000;

#[derive(Debug, Error)]
pub enum QdbError {
    #[error("http: {0}")]
    Http(#[from] reqwest::Error),
    #[error("qdb status {0}: {1}")]
    Status(u16, String),
    #[error("qdb not ready")]
    NotReady,
}

#[derive(Clone)]
pub struct Client {
    base: String,
    http: reqwest::Client,
}

impl Client {
    pub fn from_env() -> Self {
        let base = std::env::var("QDB_URL").unwrap_or_else(|_| "http://qdb:9090".into());
        Self::new(base)
    }

    pub fn new(base: impl Into<String>) -> Self {
        Self {
            base: base.into().trim_end_matches('/').to_string(),
            http: reqwest::Client::new(),
        }
    }

    pub fn base_url(&self) -> &str {
        &self.base
    }

    /// 浏览器订阅读代理目标：http(s) → ws(s) + `/v1/ws`
    pub fn ws_url(&self) -> String {
        let b = self.base.as_str();
        if let Some(rest) = b.strip_prefix("https://") {
            format!("wss://{rest}/v1/ws")
        } else if let Some(rest) = b.strip_prefix("http://") {
            format!("ws://{rest}/v1/ws")
        } else if b.starts_with("ws://") || b.starts_with("wss://") {
            format!("{}/v1/ws", b.trim_end_matches('/'))
        } else {
            format!("ws://{b}/v1/ws")
        }
    }

    pub async fn wait_ready(&self, attempts: u32) -> Result<(), QdbError> {
        for _ in 0..attempts {
            match self
                .http
                .get(format!("{}/v1/snapshots", self.base))
                .timeout(std::time::Duration::from_secs(2))
                .send()
                .await
            {
                Ok(r) if r.status().is_success() => return Ok(()),
                _ => {
                    std::thread::sleep(std::time::Duration::from_secs(1));
                }
            }
        }
        Err(QdbError::NotReady)
    }

    pub async fn snapshots(&self, symbols: Option<&[String]>) -> Result<Vec<Value>, QdbError> {
        let mut req = self
            .http
            .get(format!("{}/v1/snapshots", self.base))
            .timeout(std::time::Duration::from_secs(5));
        if let Some(syms) = symbols {
            if !syms.is_empty() {
                req = req.query(&[("symbols", syms.join(","))]);
            }
        }
        let resp = req.send().await?;
        if !resp.status().is_success() {
            return Err(QdbError::Status(
                resp.status().as_u16(),
                resp.text().await.unwrap_or_default(),
            ));
        }
        let body: Value = resp.json().await?;
        Ok(body
            .get("data")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default())
    }

    pub async fn klines(&self, symbol: &str, period: &str) -> Vec<Value> {
        let Ok(resp) = self
            .http
            .get(format!("{}/v1/klines", self.base))
            .query(&[("symbol", symbol), ("period", period)])
            .timeout(std::time::Duration::from_secs(5))
            .send()
            .await
        else {
            return Vec::new();
        };
        if !resp.status().is_success() {
            return Vec::new();
        }
        let body: Value = resp.json().await.unwrap_or(json!({}));
        body.get("data")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default()
    }

    pub async fn get_doc(&self, key: &str) -> Option<Value> {
        let resp = self
            .http
            .get(format!("{}/v1/docs", self.base))
            .query(&[("key", key)])
            .timeout(std::time::Duration::from_secs(3))
            .send()
            .await
            .ok()?;
        if !resp.status().is_success() {
            return None;
        }
        resp.json().await.ok()
    }

    pub async fn put_docs(&self, items: &[Value]) -> Result<u64, QdbError> {
        if items.is_empty() {
            return Ok(0);
        }
        let resp = self
            .http
            .post(format!("{}/v1/docs", self.base))
            .json(&json!({ "items": items }))
            .timeout(std::time::Duration::from_secs(30))
            .send()
            .await?;
        self.written(resp).await
    }

    pub async fn post_quotes(&self, items: &[Value]) -> Result<u64, QdbError> {
        if items.is_empty() {
            return Ok(0);
        }
        let resp = self
            .http
            .post(format!("{}/v1/quotes", self.base))
            .json(&json!({ "items": items }))
            .timeout(std::time::Duration::from_secs(60))
            .send()
            .await?;
        self.written(resp).await
    }

    pub async fn post_trades(&self, items: &[Value]) -> Result<u64, QdbError> {
        if items.is_empty() {
            return Ok(0);
        }
        let resp = self
            .http
            .post(format!("{}/v1/trades", self.base))
            .json(&json!({ "items": items }))
            .timeout(std::time::Duration::from_secs(120))
            .send()
            .await?;
        self.written(resp).await
    }

    async fn written(&self, resp: reqwest::Response) -> Result<u64, QdbError> {
        if !resp.status().is_success() {
            return Err(QdbError::Status(
                resp.status().as_u16(),
                resp.text().await.unwrap_or_default(),
            ));
        }
        let body: Value = resp.json().await.unwrap_or(json!({}));
        Ok(body.get("written").and_then(|v| v.as_u64()).unwrap_or(0))
    }
}

pub fn scale(value: f64) -> i64 {
    (value * PRICE_SCALE as f64).round() as i64
}

pub fn unscale(raw: i64) -> f64 {
    raw as f64 / PRICE_SCALE as f64
}
