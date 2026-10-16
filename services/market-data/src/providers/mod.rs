//! 行情数据源适配层（Provider Adapter）。
//!
//! 上层只依赖 [`MarketDataProvider`]，底层可切换 mock / AlphaFeed / TickFlow 等，
//! 避免编排层与 MCP 绑定具体上游协议。

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub mod alpha_feed;
pub mod mock;

/// 实时（或准实时）行情快照，字段对齐立项文档中的 Quote DTO。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Quote {
    pub symbol: String,
    pub name: String,
    pub last_price: f64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: i64,
    pub amount: f64,
    pub change_pct: f64,
    /// Unix 秒时间戳。
    pub timestamp: i64,
}

/// OHLCV K 线一根。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Bar {
    pub symbol: String,
    /// 周期标识，如 `1d` / `1m`。
    pub period: String,
    pub datetime: String,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: i64,
    pub amount: f64,
}

/// Provider 侧错误：区分「标的不存在」与「上游不可用」，便于 HTTP 映射。
#[derive(Debug, Error)]
pub enum ProviderError {
    #[error("upstream error: {0}")]
    Upstream(String),
    #[error("not found: {0}")]
    NotFound(String),
}

/// 统一行情 Provider 接口；实现须线程安全以便放入 `Arc`。
#[async_trait]
pub trait MarketDataProvider: Send + Sync {
    /// 单标的最新报价。
    async fn get_quote(&self, symbol: &str) -> Result<Quote, ProviderError>;

    /// 批量报价（默认实现可循环调用 `get_quote`）。
    async fn get_quotes(&self, symbols: &[&str]) -> Result<Vec<Quote>, ProviderError>;

    /// 历史 K 线。
    ///
    /// - `period`：如 `1d`
    /// - `count`：根数上限由具体实现裁剪
    /// - `adjust`：复权方式（`none` / `qfq` / `hfq` 等，视上游而定）
    async fn get_bars(
        &self,
        symbol: &str,
        period: &str,
        count: usize,
        adjust: &str,
    ) -> Result<Vec<Bar>, ProviderError>;

    /// 按关键字搜索标的，返回可展示的报价摘要列表。
    async fn search(&self, q: &str) -> Result<Vec<Quote>, ProviderError>;
}
