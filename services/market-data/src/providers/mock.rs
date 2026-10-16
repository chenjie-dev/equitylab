//! 确定性 Mock Provider：本地 / CI 无需 API Key 即可联调。
//!
//! 对常见 A 股代码给出固定基准价，其余符号回落为 100；K 线为可重复的合成序列。

use super::{Bar, MarketDataProvider, ProviderError, Quote};
use async_trait::async_trait;
use chrono::Utc;

/// 无状态 Mock 实现。
#[derive(Default)]
pub struct MockProvider;

#[async_trait]
impl MarketDataProvider for MockProvider {
    async fn get_quote(&self, symbol: &str) -> Result<Quote, ProviderError> {
        Ok(demo_quote(symbol))
    }

    async fn get_quotes(&self, symbols: &[&str]) -> Result<Vec<Quote>, ProviderError> {
        Ok(symbols.iter().map(|s| demo_quote(s)).collect())
    }

    async fn get_bars(
        &self,
        symbol: &str,
        period: &str,
        count: usize,
        _adjust: &str,
    ) -> Result<Vec<Bar>, ProviderError> {
        // 上限 252：约一年交易日，足够 20/60 双均线演示。
        let n = count.min(252);
        let mut bars = Vec::with_capacity(n);
        let base = demo_quote(symbol).last_price;
        let start = chrono::NaiveDate::from_ymd_opt(2024, 1, 2).expect("valid date");
        let mut px = base;
        for i in 0..n {
            let t = i as f64;
            // 缓升趋势 + 慢波 + 快噪，便于金叉/死叉出现可观察净值变化。
            let target =
                base * (1.0 + 0.0006 * t + 0.05 * (t * 0.12).sin() + 0.01 * (t * 0.55).sin());
            let open = px;
            let close = open * 0.65 + target * 0.35;
            let day = start + chrono::Duration::days(i as i64);
            bars.push(Bar {
                symbol: symbol.to_string(),
                period: period.to_string(),
                datetime: day.format("%Y-%m-%d").to_string(),
                open,
                high: open.max(close) * 1.01,
                low: open.min(close) * 0.99,
                close,
                volume: 1_000_000 + i as i64 * 1000,
                amount: close * 1_000_000.0,
            });
            px = close;
        }
        Ok(bars)
    }

    async fn search(&self, q: &str) -> Result<Vec<Quote>, ProviderError> {
        let candidates = ["600519.SH", "300750.SZ", "000001.SZ", "AAPL"];
        Ok(candidates
            .into_iter()
            .filter(|s| s.to_lowercase().contains(&q.to_lowercase()) || q.is_empty())
            .map(demo_quote)
            .collect())
    }
}

/// 按 symbol 映射演示基准价；未知代码统一 100，便于识别「未命中知名标的」。
fn demo_quote(symbol: &str) -> Quote {
    let base = match symbol {
        "600519.SH" => 1680.0,
        "300750.SZ" => 190.0,
        "000001.SZ" => 11.2,
        _ => 100.0,
    };
    Quote {
        symbol: symbol.to_string(),
        name: format!("DEMO-{symbol}"),
        last_price: base,
        open: base * 0.99,
        high: base * 1.02,
        low: base * 0.98,
        close: base,
        volume: 2_500_000,
        amount: base * 2_500_000.0,
        change_pct: 1.25,
        timestamp: Utc::now().timestamp(),
    }
}
