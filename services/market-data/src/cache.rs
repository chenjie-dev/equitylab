//! 实时报价 Redis 缓存层（对齐 redis-core：显式 key 命名空间 + TTL）。
//!
//! Key：`equitylab:md:quote:{symbol}`  
//! 连接失败时使用 [`QuoteCache::disabled`]，读写均为空操作。

use crate::providers::Quote;
use redis::aio::ConnectionManager;
use redis::AsyncCommands;

/// 立项约定：实时快照 TTL 3 秒。
pub const QUOTE_TTL_SECS: u64 = 3;

fn quote_key(symbol: &str) -> String {
    format!("equitylab:md:quote:{symbol}")
}

/// 可选 Redis 连接；`client == None` 表示禁用缓存。
pub struct QuoteCache {
    client: Option<ConnectionManager>,
}

impl QuoteCache {
    /// 建立与 Redis 的异步连接管理器。
    pub async fn connect(redis_url: &str) -> Result<Self, redis::RedisError> {
        let client = redis::Client::open(redis_url)?;
        let manager = ConnectionManager::new(client).await?;
        Ok(Self {
            client: Some(manager),
        })
    }

    /// 无 Redis 时的降级实例：get 恒为 None，set 为空操作。
    pub fn disabled() -> Self {
        Self { client: None }
    }

    /// 读取缓存报价；反序列化失败或 miss 时返回 `None`。
    pub async fn get(&self, symbol: &str) -> Option<Quote> {
        let mut conn = self.client.clone()?;
        let key = quote_key(symbol);
        let raw: Option<String> = conn.get(key).await.ok()?;
        raw.and_then(|s| serde_json::from_str(&s).ok())
    }

    /// 写入报价并设置过期时间（秒）。禁用缓存或序列化失败时静默忽略。
    pub async fn set(&self, symbol: &str, quote: &Quote, ttl_secs: u64) {
        let Some(mut conn) = self.client.clone() else {
            return;
        };
        let key = quote_key(symbol);
        if let Ok(payload) = serde_json::to_string(quote) {
            let _: Result<(), _> = conn.set_ex(key, payload, ttl_secs).await;
        }
    }
}
