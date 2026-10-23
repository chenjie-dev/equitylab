//! AlphaFeed Provider：读路径禁止外呼；请用 `MARKET_PROVIDER=binance|mock` + qdb。

use super::{Bar, MarketDataProvider, ProviderError, Quote};
use async_trait::async_trait;

/// 骨架保留以便 env 切换不崩；一律拒绝上游 HTTP。
pub struct AlphaFeedProvider;

impl AlphaFeedProvider {
    pub fn from_env() -> Self {
        Self
    }
}

fn refused(what: &str) -> ProviderError {
    ProviderError::Upstream(format!(
        "qdb-only: AlphaFeed {what} refused; set MARKET_PROVIDER=binance|mock and read qdb"
    ))
}

#[async_trait]
impl MarketDataProvider for AlphaFeedProvider {
    async fn get_quote(&self, _symbol: &str) -> Result<Quote, ProviderError> {
        Err(refused("get_quote"))
    }

    async fn get_quotes(&self, _symbols: &[&str]) -> Result<Vec<Quote>, ProviderError> {
        Err(refused("get_quotes"))
    }

    async fn get_bars(
        &self,
        _symbol: &str,
        _period: &str,
        _count: usize,
        _adjust: &str,
    ) -> Result<Vec<Bar>, ProviderError> {
        Err(refused("get_bars"))
    }

    async fn search(&self, _q: &str) -> Result<Vec<Quote>, ProviderError> {
        Err(refused("search"))
    }
}
