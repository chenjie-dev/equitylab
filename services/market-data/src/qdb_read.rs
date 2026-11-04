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

/// 取 docs / 引擎折叠后的**最后一根**（供与 PG 历史拼接当日未闭合棒）。
///
/// 全市场 REST K 线轮转很慢时 docs 会停在旧桶；用实时 `binance:ticker` 补当前桶，
/// 避免图表卡在「整点闭合棒」而报价已前进数十分钟。
pub async fn binance_last_bar(symbol: &str, interval: &str) -> Option<Value> {
    let mut last: Option<Value> = None;
    let key = format!("binance:kline:{symbol}:{interval}");
    if let Some(doc) = doc(&key).await {
        if let Some(rows) = doc_kline_rows(&doc) {
            last = rows.into_iter().last();
        }
    }
    if last.is_none() {
        let (period, group) = map_interval(interval);
        let raw_limit = group.saturating_mul(2).max(2).min(64);
        let rows = client()
            .klines_window(
                &format!("BINANCE:{symbol}"),
                period,
                Some(raw_limit),
                None,
            )
            .await;
        let folded = fold(&rows, group);
        last = folded.last().and_then(to_binance_row);
    }
    let price = ticker_last_price(symbol).await;
    match (last, price) {
        (Some(row), Some(px)) => Some(align_tail_with_ticker(row, interval, px)),
        (Some(row), None) => Some(row),
        (None, Some(px)) => forming_bar_from_price(interval, px),
        (None, None) => None,
    }
}

async fn ticker_last_price(symbol: &str) -> Option<f64> {
    let t = doc(&format!("binance:ticker:{symbol}")).await?;
    t.get("lastPrice").and_then(num)
}

fn interval_bucket_ms(interval: &str) -> u64 {
    match interval {
        "1m" => 60_000,
        "3m" => 180_000,
        "5m" => 300_000,
        "15m" => 900_000,
        "30m" => 1_800_000,
        "1h" => 3_600_000,
        "2h" => 7_200_000,
        "4h" => 14_400_000,
        "6h" => 21_600_000,
        "12h" => 43_200_000,
        "1d" => 86_400_000,
        "3d" => 259_200_000,
        "1w" => 604_800_000,
        // 月线桶粗略按 30d；仅用于未闭合末棒对齐
        "1M" => 2_592_000_000,
        _ => 3_600_000,
    }
}

fn now_ms() -> u64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn align_tail_with_ticker(row: Value, interval: &str, price: f64) -> Value {
    let iv = interval_bucket_ms(interval);
    let bucket = now_ms() / iv * iv;
    let open_ms = row_open_time_ms(&row).unwrap_or(0);
    let px = format!("{price}");
    if open_ms == bucket {
        // 同桶：抬高/压低极值并刷新收盘
        let o = row.get(1).cloned().unwrap_or(json!(px.clone()));
        let h0 = row.get(2).and_then(num).unwrap_or(price);
        let l0 = row.get(3).and_then(num).unwrap_or(price);
        let vol = row.get(5).cloned().unwrap_or(json!("0"));
        return json!([
            bucket,
            o,
            format!("{}", h0.max(price)),
            format!("{}", l0.min(price)),
            px,
            vol
        ]);
    }
    if open_ms < bucket {
        let prev_close = row
            .get(4)
            .and_then(num)
            .map(|c| format!("{c}"))
            .unwrap_or_else(|| px.clone());
        return json!([bucket, prev_close, px.clone(), px.clone(), px, "0"]);
    }
    row
}

fn forming_bar_from_price(interval: &str, price: f64) -> Option<Value> {
    let iv = interval_bucket_ms(interval);
    if iv == 0 {
        return None;
    }
    let bucket = now_ms() / iv * iv;
    let px = format!("{price}");
    Some(json!([bucket, px.clone(), px.clone(), px.clone(), px, "0"]))
}

/// 旧路径：仅 qdb docs/引擎（历史权威已迁 PG；保留给排障）。
pub async fn binance_klines(
    symbol: &str,
    interval: &str,
    limit: usize,
    end_time_ms: Option<u64>,
) -> Vec<Value> {
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
