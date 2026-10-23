//! 币安现货读适配：只读 qdb（docs / klines），禁止回源 REST。

use crate::providers::ProviderError;
use serde::Deserialize;
use serde_json::Value;
use std::collections::HashMap;

/// 币安读路径适配器；`Clone` 廉价，亦可包在 `Arc` 中共享。
#[derive(Clone, Default)]
pub struct Client;

impl Client {
    pub fn from_env() -> Self {
        Self
    }

    /// 读路径禁止回源币安。历史方法保留签名，一律拒绝外呼。
    pub async fn get_v3(
        &self,
        path: &str,
        _query: &HashMap<String, String>,
    ) -> Result<Value, ProviderError> {
        Err(ProviderError::Upstream(format!(
            "qdb-only: refusing upstream GET /api/v3/{path}; use qdb docs/snapshots/klines"
        )))
    }

    pub async fn ticker_24hr(&self, symbol: &str) -> Result<Ticker24hr, ProviderError> {
        let sym = normalize_symbol(symbol);
        let v = crate::qdb_read::doc(&format!("binance:ticker:{sym}"))
            .await
            .ok_or_else(|| ProviderError::NotFound(format!("no qdb ticker {sym}")))?;
        serde_json::from_value(v)
            .map_err(|e| ProviderError::Upstream(format!("ticker parse: {e}")))
    }

    pub async fn klines(
        &self,
        symbol: &str,
        interval: &str,
        limit: usize,
    ) -> Result<Vec<Value>, ProviderError> {
        let sym = normalize_symbol(symbol);
        let rows =
            crate::qdb_read::binance_klines(&sym, &map_interval(interval), limit.clamp(1, 1000), None)
                .await;
        Ok(rows)
    }

    /// 优先 docs `binance:exchangeInfo`；缺则返回 collector 常见 USDT 列表（不回源）。
    pub async fn exchange_info(&self) -> Result<Value, ProviderError> {
        if let Some(v) = crate::qdb_read::doc("binance:exchangeInfo").await {
            return Ok(v);
        }
        let symbols: Vec<Value> = default_spot_symbols()
            .into_iter()
            .map(|s| {
                serde_json::json!({
                    "symbol": s,
                    "status": "TRADING",
                    "quoteAsset": "USDT",
                })
            })
            .collect();
        Ok(serde_json::json!({
            "timezone": "UTC",
            "serverTime": chrono_like_millis(),
            "symbols": symbols,
            "source": "qdb-fallback",
        }))
    }
}

fn chrono_like_millis() -> i64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

fn default_spot_symbols() -> Vec<&'static str> {
    vec![
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
        "AVAXUSDT", "DOTUSDT", "LINKUSDT", "POLUSDT", "LTCUSDT", "NEARUSDT", "UNIUSDT",
        "ATOMUSDT", "APTUSDT",
    ]
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
