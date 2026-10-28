//! 浏览器 WebSocket 经网关转发到 market-data `/qdb/ws`（再代理 qdb）。
//! 鉴权落地后可在此统一校验 Upgrade 请求。

use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        State,
    },
    http::StatusCode,
    response::IntoResponse,
};
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tokio_tungstenite::{connect_async, tungstenite::Message as TMessage};

use crate::AppState;

/// `GET /api/market/qdb/ws`（及 exchanges 别名）→ market-data 同名路径。
pub async fn qdb_ws(
    State(state): State<Arc<AppState>>,
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    let base = state.market_data_url.trim_end_matches('/');
    let http = if base.starts_with("https://") {
        base.replacen("https://", "wss://", 1)
    } else {
        base.replacen("http://", "ws://", 1)
    };
    let upstream_url = format!("{http}/qdb/ws");
    ws.on_upgrade(move |socket| proxy_socket(socket, upstream_url))
}

async fn proxy_socket(client_ws: WebSocket, upstream_url: String) {
    tracing::info!(%upstream_url, service = "gateway", "ws proxy connecting");

    let (upstream, _) = match connect_async(&upstream_url).await {
        Ok(v) => v,
        Err(e) => {
            let (mut sink, _) = client_ws.split();
            let _ = sink
                .send(Message::Text(
                    format!(r#"{{"type":"error","message":"upstream ws failed: {e}"}}"#).into(),
                ))
                .await;
            let _ = sink.close().await;
            return;
        }
    };

    let (mut client_sink, mut client_stream) = client_ws.split();
    let (mut up_sink, mut up_stream) = upstream.split();

    let to_client = tokio::spawn(async move {
        while let Some(Ok(msg)) = up_stream.next().await {
            let out = match msg {
                TMessage::Text(t) => Message::Text(t.to_string().into()),
                TMessage::Binary(b) => Message::Binary(b),
                TMessage::Ping(p) => Message::Ping(p),
                TMessage::Pong(p) => Message::Pong(p),
                TMessage::Close(_) => break,
                TMessage::Frame(_) => continue,
            };
            if client_sink.send(out).await.is_err() {
                break;
            }
        }
    });

    let to_upstream = tokio::spawn(async move {
        while let Some(Ok(msg)) = client_stream.next().await {
            let out = match msg {
                Message::Text(t) => TMessage::Text(t.to_string().into()),
                Message::Binary(b) => TMessage::Binary(b),
                Message::Ping(p) => TMessage::Ping(p),
                Message::Pong(p) => TMessage::Pong(p),
                Message::Close(_) => break,
            };
            if up_sink.send(out).await.is_err() {
                break;
            }
        }
    });

    tokio::select! {
        _ = to_client => {},
        _ = to_upstream => {},
    }
}

/// 非 Upgrade 误打 WS 路径时返回 426。
pub async fn qdb_ws_http_fallback() -> (StatusCode, &'static str) {
    (
        StatusCode::UPGRADE_REQUIRED,
        "WebSocket upgrade required; use ws(s)://…/api/market/qdb/ws",
    )
}
