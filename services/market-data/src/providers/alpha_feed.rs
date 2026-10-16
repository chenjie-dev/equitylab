//! AlphaFeed REST Provider 骨架。
//!
//! 配置：`ALPHAFEED_API_KEY`、`ALPHAFEED_BASE_URL`。
//! 未配置 Key 时返回清晰的 Upstream 错误，避免静默失败。
//!
//! TODO(mvp)：补齐 get_bars / search，并与真实上游字段对齐。

use super::{Bar, MarketDataProvider, ProviderError, Quote};
use async_trait::async_trait;
use serde::Deserialize;

/// AlphaFeed 适配器：Bearer Token 调用 REST。
pub struct AlphaFeedProvider {
    client: reqwest::Client,
    base_url: String,
    api_key: String,
}

impl AlphaFeedProvider {
    /// 从环境变量构造；Key 可为空（调用时再报错）。
    pub fn from_env() -> Self {
        Self {
            client: reqwest::Client::new(),
            base_url: std::env::var("ALPHAFEED_BASE_URL")
                .unwrap_or_else(|_| "https://api.alphafeed.org/v1".into()),
            api_key: std::env::var("ALPHAFEED_API_KEY").unwrap_or_default(),
        }
    }
}

/// 上游 JSON 子集；缺省字段用 0 / 空串，降低 schema 漂移导致的解析失败。
#[derive(Deserialize)]
struct UpstreamQuote {
    symbol: String,
    #[serde(default)]
    name: String,
    last_price: f64,
    #[serde(default)]
    open: f64,
    #[serde(default)]
    high: f64,
    #[serde(default)]
    low: f64,
    #[serde(default)]
    close: f64,
    #[serde(default)]
    volume: i64,
    #[serde(default)]
    amount: f64,
    #[serde(default)]
    change_pct: f64,
    #[serde(default)]
    timestamp: i64,
}

#[async_trait]
impl MarketDataProvider for AlphaFeedProvider {
    async fn get_quote(&self, symbol: &str) -> Result<Quote, ProviderError> {
        if self.api_key.is_empty() {
            return Err(ProviderError::Upstream(
                "ALPHAFEED_API_KEY not configured".into(),
            ));
        }
        let url = format!("{}/quotes/{}", self.base_url.trim_end_matches('/'), symbol);
        let resp = self
            .client
            .get(url)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .send()
            .await
            .map_err(|e| ProviderError::Upstream(e.to_string()))?;
        if !resp.status().is_success() {
            return Err(ProviderError::Upstream(format!("status {}", resp.status())));
        }
        let q: UpstreamQuote = resp
            .json()
            .await
            .map_err(|e| ProviderError::Upstream(e.to_string()))?;
        Ok(Quote {
            symbol: q.symbol,
            name: q.name,
            last_price: q.last_price,
            open: q.open,
            high: q.high,
            low: q.low,
            close: q.close,
            volume: q.volume,
            amount: q.amount,
            change_pct: q.change_pct,
            timestamp: q.timestamp,
        })
    }

    async fn get_quotes(&self, symbols: &[&str]) -> Result<Vec<Quote>, ProviderError> {
        // MVP：串行拉取；上游提供批量接口后再优化并发与配额。
        let mut out = Vec::new();
        for s in symbols {
            out.push(self.get_quote(s).await?);
        }
        Ok(out)
    }

    async fn get_bars(
        &self,
        _symbol: &str,
        _period: &str,
        _count: usize,
        _adjust: &str,
    ) -> Result<Vec<Bar>, ProviderError> {
        Err(ProviderError::Upstream(
            "AlphaFeed get_bars not implemented in MVP skeleton".into(),
        ))
    }

    async fn search(&self, _q: &str) -> Result<Vec<Quote>, ProviderError> {
        Err(ProviderError::Upstream(
            "AlphaFeed search not implemented in MVP skeleton".into(),
        ))
    }
}
