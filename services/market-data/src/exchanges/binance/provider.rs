//! 将币安行情适配为统一 [`MarketDataProvider`]。

use super::client::{map_interval, normalize_symbol, Client};
use crate::providers::{Bar, MarketDataProvider, ProviderError, Quote};
use async_trait::async_trait;
use chrono::{TimeZone, Utc};
use serde_json::Value;
use std::sync::Arc;

pub struct Provider {
    client: Arc<Client>,
}

impl Provider {
    pub fn new(client: Arc<Client>) -> Self {
        Self { client }
    }
}

fn parse_f64(s: &str) -> f64 {
    s.parse().unwrap_or(0.0)
}

fn parse_i64_vol(s: &str) -> i64 {
    parse_f64(s).round() as i64
}

fn kline_to_bar(symbol: &str, period: &str, row: &Value) -> Option<Bar> {
    let a = row.as_array()?;
    if a.len() < 7 {
        return None;
    }
    let open_time = a[0].as_i64().unwrap_or(0);
    let open = a[1].as_str().and_then(|s| s.parse().ok()).unwrap_or(0.0);
    let high = a[2].as_str().and_then(|s| s.parse().ok()).unwrap_or(0.0);
    let low = a[3].as_str().and_then(|s| s.parse().ok()).unwrap_or(0.0);
    let close = a[4].as_str().and_then(|s| s.parse().ok()).unwrap_or(0.0);
    let volume = a[5]
        .as_str()
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or(0.0)
        .round() as i64;
    let amount = a
        .get(7)
        .and_then(|v| v.as_str())
        .and_then(|s| s.parse().ok())
        .unwrap_or(0.0);
    let dt = Utc
        .timestamp_millis_opt(open_time)
        .single()
        .map(|t| t.format("%Y-%m-%dT%H:%M:%SZ").to_string())
        .unwrap_or_else(|| open_time.to_string());
    Some(Bar {
        symbol: symbol.to_string(),
        period: period.to_string(),
        datetime: dt,
        open,
        high,
        low,
        close,
        volume,
        amount,
    })
}

#[async_trait]
impl MarketDataProvider for Provider {
    async fn get_quote(&self, symbol: &str) -> Result<Quote, ProviderError> {
        let sym = normalize_symbol(symbol);
        let t = self.client.ticker_24hr(&sym).await?;
        let last = parse_f64(&t.last_price);
        Ok(Quote {
            symbol: t.symbol,
            name: format!("BINANCE-{sym}"),
            last_price: last,
            open: parse_f64(&t.open_price),
            high: parse_f64(&t.high_price),
            low: parse_f64(&t.low_price),
            close: last,
            volume: parse_i64_vol(&t.volume),
            amount: parse_f64(&t.quote_volume),
            change_pct: parse_f64(&t.price_change_percent),
            timestamp: if t.close_time > 1_000_000_000_000 {
                t.close_time / 1000
            } else {
                t.close_time
            },
        })
    }

    async fn get_quotes(&self, symbols: &[&str]) -> Result<Vec<Quote>, ProviderError> {
        let mut out = Vec::with_capacity(symbols.len());
        for s in symbols {
            out.push(self.get_quote(s).await?);
        }
        Ok(out)
    }

    async fn get_bars(
        &self,
        symbol: &str,
        period: &str,
        count: usize,
        _adjust: &str,
    ) -> Result<Vec<Bar>, ProviderError> {
        let sym = normalize_symbol(symbol);
        let interval = map_interval(period);
        let rows = self.client.klines(&sym, &interval, count).await?;
        Ok(rows
            .iter()
            .filter_map(|r| kline_to_bar(&sym, &interval, r))
            .collect())
    }

    async fn search(&self, q: &str) -> Result<Vec<Quote>, ProviderError> {
        let needle = q.trim().to_uppercase().replace('/', "");
        let info = self.client.exchange_info().await?;
        let symbols = info
            .get("symbols")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let mut matches: Vec<String> = symbols
            .iter()
            .filter_map(|s| {
                let sym = s.get("symbol")?.as_str()?;
                let status = s.get("status").and_then(|v| v.as_str()).unwrap_or("");
                if status != "TRADING" {
                    return None;
                }
                if needle.is_empty() || sym.contains(&needle) {
                    Some(sym.to_string())
                } else {
                    None
                }
            })
            .take(20)
            .collect();
        if matches.is_empty() && needle.is_empty() {
            matches = vec![
                "BTCUSDT".into(),
                "ETHUSDT".into(),
                "BNBUSDT".into(),
                "SOLUSDT".into(),
            ];
        }
        let mut out = Vec::new();
        for sym in matches.into_iter().take(8) {
            match self.get_quote(&sym).await {
                Ok(q) => out.push(q),
                Err(e) => tracing::warn!(symbol = %sym, error = %e, "binance search quote skip"),
            }
        }
        Ok(out)
    }
}
