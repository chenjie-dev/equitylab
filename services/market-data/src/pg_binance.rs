//! 币安现货冷 K 线：只读 Postgres `market.bar_*`（exchange=BINANCE）。
//! 禁止查 A 股；禁止回源上游。

use serde_json::{json, Value};
use sqlx::postgres::PgPoolOptions;
use sqlx::{PgPool, Row};
use std::sync::OnceLock;
use tracing::{info, warn};

static POOL: OnceLock<Option<PgPool>> = OnceLock::new();

fn pool() -> Option<&'static PgPool> {
    POOL.get().and_then(|o| o.as_ref())
}

/// 在 tokio runtime 内初始化连接池（main 启动时调用一次）。
pub async fn init() {
    if POOL.get().is_some() {
        return;
    }
    let url = match std::env::var("DATABASE_URL") {
        Ok(u) if !u.trim().is_empty() => u,
        _ => {
            warn!(target: "equitylab.market_data", "DATABASE_URL unset; BINANCE PG history disabled");
            let _ = POOL.set(None);
            return;
        }
    };
    match PgPoolOptions::new()
        .max_connections(4)
        .acquire_timeout(std::time::Duration::from_secs(5))
        .connect(&url)
        .await
    {
        Ok(p) => {
            info!(target: "equitylab.market_data", "pg pool ready for BINANCE bars");
            let _ = POOL.set(Some(p));
        }
        Err(e) => {
            warn!(target: "equitylab.market_data", error = %e, "DATABASE_URL connect failed");
            let _ = POOL.set(None);
        }
    }
}

fn normalize_period(interval: &str) -> &str {
    match interval.trim() {
        "60m" => "1h",
        other => other,
    }
}

fn row_open_ms(row: &Value) -> Option<u64> {
    let cell = row.get(0)?;
    cell.as_u64()
        .or_else(|| cell.as_i64().map(|n| n as u64))
        .or_else(|| cell.as_str().and_then(|s| s.parse().ok()))
}

/// 返回币安风格数组行（升序）：`[openTime, o, h, l, c, volume, …]`。
pub async fn list_bars(
    symbol: &str,
    interval: &str,
    limit: usize,
    end_time_ms: Option<u64>,
) -> Vec<Value> {
    let Some(pool) = pool() else {
        return Vec::new();
    };
    let code = symbol.trim().to_uppercase();
    if code.is_empty() {
        return Vec::new();
    }
    let iv = normalize_period(interval);
    let lim = limit.clamp(1, 1500) as i64;
    let end = end_time_ms.map(|t| t as i64);

    let result = if iv == "1d" {
        sqlx::query(
            r#"
            SELECT
                (EXTRACT(EPOCH FROM (bd.trading_day::timestamp AT TIME ZONE 'UTC'))
                    * 1000)::bigint AS open_ms,
                bd.open::text, bd.high::text, bd.low::text, bd.close::text,
                bd.volume::text, COALESCE(bd.amount::text, '0')
            FROM market.bar_daily bd
            JOIN market.security s ON s.inner_code = bd.inner_code
            WHERE s.exchange_code = 'BINANCE' AND s.secu_code = $1
              AND ($2::bigint IS NULL
                   OR (EXTRACT(EPOCH FROM (bd.trading_day::timestamp AT TIME ZONE 'UTC'))
                       * 1000) <= $2)
            ORDER BY bd.trading_day DESC
            LIMIT $3
            "#,
        )
        .bind(&code)
        .bind(end)
        .bind(lim)
        .fetch_all(pool)
        .await
    } else {
        sqlx::query(
            r#"
            SELECT
                (EXTRACT(EPOCH FROM bm.bar_time) * 1000)::bigint AS open_ms,
                bm.open::text, bm.high::text, bm.low::text, bm.close::text,
                bm.volume::text, COALESCE(bm.amount::text, '0')
            FROM market.bar_minute bm
            JOIN market.security s ON s.inner_code = bm.inner_code
            WHERE s.exchange_code = 'BINANCE' AND s.secu_code = $1
              AND bm.period = $2
              AND ($3::bigint IS NULL
                   OR (EXTRACT(EPOCH FROM bm.bar_time) * 1000) <= $3)
            ORDER BY bm.bar_time DESC
            LIMIT $4
            "#,
        )
        .bind(&code)
        .bind(iv)
        .bind(end)
        .bind(lim)
        .fetch_all(pool)
        .await
    };

    let rows = match result {
        Ok(r) => r,
        Err(e) => {
            warn!(
                target: "equitylab.market_data",
                error = %e,
                symbol = %code,
                interval = %iv,
                "BINANCE PG bars query failed"
            );
            return Vec::new();
        }
    };

    let mut out: Vec<Value> = rows
        .into_iter()
        .map(|row| {
            let open_ms: i64 = row.get(0);
            let o: String = row.get(1);
            let h: String = row.get(2);
            let l: String = row.get(3);
            let c: String = row.get(4);
            let vol: String = row.get(5);
            let amt: String = row.get(6);
            json!([open_ms, o, h, l, c, vol, open_ms, amt])
        })
        .collect();
    out.reverse();
    out
}

/// 历史 PG + 可选 qdb 当日未闭合末棒（仅最新窗口、无 endTime 时）。
pub async fn merged_klines(
    symbol: &str,
    interval: &str,
    limit: usize,
    end_time_ms: Option<u64>,
    qdb_tail: Option<Value>,
) -> Vec<Value> {
    let limit = limit.clamp(1, 1500);
    let mut hist = list_bars(symbol, interval, limit, end_time_ms).await;

    // 左滑只读冷库；最新窗口才拼 qdb 末棒
    if end_time_ms.is_some() {
        return hist;
    }
    let Some(tail) = qdb_tail else {
        return hist;
    };
    let Some(tail_open) = row_open_ms(&tail) else {
        return hist;
    };
    let last_open = hist.last().and_then(row_open_ms);
    match last_open {
        Some(t) if t == tail_open => {
            // 同开盘时间：用 qdb 覆盖（可能含未闭合更新）
            if let Some(last) = hist.last_mut() {
                *last = tail;
            }
        }
        Some(t) if t < tail_open => {
            hist.push(tail);
            if hist.len() > limit {
                let start = hist.len() - limit;
                hist = hist[start..].to_vec();
            }
        }
        None => {
            hist.push(tail);
        }
        _ => {}
    }
    hist
}
