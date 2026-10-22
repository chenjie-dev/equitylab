//! 行情只读 qdb（经 equitylab-qdb）。币安/RWA K 线折叠属本服务 adapter。
//! K 线按窗口读（limit + endTime），对齐主流行情台：首屏少拉、左滑补历史。

use equitylab_qdb::Client;
use serde_json::{json, Value};
use std::sync::OnceLock;

fn client() -> &'static Client {
    static C: OnceLock<Client> = OnceLock::new();
    C.get_or_init(Client::from_env)
}

pub async fn doc(key: &str) -> Option<Value> {
    client().get_doc(key).await
}

pub async fn klines(symbol: &str, period: &str) -> Vec<Value> {
    client().klines(symbol, period).await
}

/// 把 qdb K 线折成币安数组：`[openTime, open, high, low, close, volume]`。
///
/// 优先读 collector 写入的 `binance:kline:{symbol}:{interval}` docs（可含历史）；
/// 引擎聚合 K 线受 late-tick 限制，水位推进后无法靠回补 trades 填满首屏。
///
/// - `limit`：目标根数（折叠后）
/// - `end_time_ms`：只要开盘时间 ≤ 该毫秒的桶（向前翻页时传「当前最老一根 - 1」）
pub async fn binance_klines(
    symbol: &str,
    interval: &str,
    limit: usize,
    end_time_ms: Option<u64>,
) -> Vec<Value> {
    // 与 collector docs 保留上限对齐，禁止一次拉爆内存
    let limit = limit.clamp(1, 500);
    let key = format!("binance:kline:{symbol}:{interval}");
    if let Some(doc) = doc(&key).await {
        if let Some(rows) = doc_kline_rows(&doc) {
            let filtered: Vec<Value> = rows
                .into_iter()
                .filter(|row| match end_time_ms {
                    None => true,
                    Some(end) => row_open_time_ms(row).map(|t| t <= end).unwrap_or(false),
                })
                .collect();
            let start = filtered.len().saturating_sub(limit);
            return filtered[start..].to_vec();
        }
    }
    let (period, group) = map_interval(interval);
    // 折叠会吞掉 group 根原生桶，多取一点原生行
    let raw_limit = limit.saturating_mul(group).saturating_add(group).min(5_000);
    let rows = client()
        .klines_window(
            &format!("BINANCE:{symbol}"),
            period,
            Some(raw_limit),
            end_time_ms,
        )
        .await;
    let folded = fold(&rows, group);
    let start = folded.len().saturating_sub(limit);
    folded[start..]
        .iter()
        .filter_map(to_binance_row)
        .collect()
}

fn doc_kline_rows(doc: &Value) -> Option<Vec<Value>> {
    if let Some(arr) = doc.as_array() {
        return Some(arr.clone());
    }
    doc.get("data").and_then(|v| v.as_array()).map(|a| a.clone())
}

fn row_open_time_ms(row: &Value) -> Option<u64> {
    let cell = row.get(0)?;
    cell.as_u64()
        .or_else(|| cell.as_i64().map(|n| n as u64))
        .or_else(|| cell.as_str().and_then(|s| s.parse().ok()))
}

pub async fn rwa_klines(
    ticker: &str,
    interval: &str,
    limit: usize,
    end_time_ms: Option<u64>,
) -> Vec<Value> {
    let (period, group) = map_interval(interval);
    let limit = limit.clamp(1, 300);
    let raw_limit = limit.saturating_mul(group).saturating_add(group).min(5_000);
    let rows = client()
        .klines_window(
            &format!("ONDO:{ticker}"),
            period,
            Some(raw_limit),
            end_time_ms,
        )
        .await;
    let folded = fold(&rows, group);
    let start = folded.len().saturating_sub(limit);
    folded[start..].iter().filter_map(to_binance_row).collect()
}

fn map_interval(interval: &str) -> (&'static str, usize) {
    match interval {
        "1m" => ("1m", 1),
        "3m" => ("1m", 3),
        "5m" => ("5m", 1),
        "15m" => ("15m", 1),
        "30m" => ("15m", 2),
        "1h" => ("1h", 1),
        "2h" => ("1h", 2),
        "4h" => ("4h", 1),
        "6h" => ("1h", 6),
        "12h" => ("4h", 3),
        "1d" => ("1d", 1),
        "3d" => ("1d", 3),
        "1w" => ("1d", 7),
        "1M" => ("1d", 30),
        _ => ("1h", 1),
    }
}

fn fold(rows: &[Value], group: usize) -> Vec<Value> {
    if group <= 1 {
        return rows.to_vec();
    }
    let mut out = Vec::new();
    let mut chunk: Vec<&Value> = Vec::new();
    for row in rows {
        chunk.push(row);
        if chunk.len() == group {
            if let Some(merged) = merge(&chunk) {
                out.push(merged);
            }
            chunk.clear();
        }
    }
    if let Some(merged) = merge(&chunk) {
        out.push(merged);
    }
    out
}

fn merge(chunk: &[&Value]) -> Option<Value> {
    let first = chunk.first()?;
    let last = chunk.last()?;
    let high = chunk
        .iter()
        .filter_map(|r| r.get("high").and_then(num))
        .fold(f64::MIN, f64::max);
    let low = chunk
        .iter()
        .filter_map(|r| r.get("low").and_then(num))
        .fold(f64::MAX, f64::min);
    let volume: f64 = chunk
        .iter()
        .filter_map(|r| r.get("volume").and_then(num))
        .sum();
    Some(json!({
        "ts": first.get("ts"),
        "open": first.get("open"),
        "high": high,
        "low": low,
        "close": last.get("close"),
        "volume": volume,
    }))
}

fn to_binance_row(row: &Value) -> Option<Value> {
    let ts_ns = row.get("ts")?.as_i64()?;
    let open_ms = ts_ns / 1_000_000;
    Some(json!([
        open_ms,
        json_num(row.get("open")?),
        json_num(row.get("high")?),
        json_num(row.get("low")?),
        json_num(row.get("close")?),
        json_num(row.get("volume")?),
    ]))
}

fn json_num(v: &Value) -> String {
    match v {
        Value::Number(n) => n.to_string(),
        Value::String(s) => s.clone(),
        _ => "0".into(),
    }
}

fn num(v: &Value) -> Option<f64> {
    v.as_f64()
        .or_else(|| v.as_str().and_then(|s| s.parse().ok()))
}
