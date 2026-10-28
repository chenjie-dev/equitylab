//! 代理 WebSocket 到 qdb `GET /v1/ws`（SELECT … SUBSCRIBE）。
//! 浏览器应经 gateway `/api/market/qdb/ws`；本路径供网关回源与内网调试。

use axum::{
    extract::ws::{Message, WebSocket, WebSocketUpgrade},
    response::IntoResponse,
};
use equitylab_qdb::Client;
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{connect_async, tungstenite::Message as TMessage};

pub async fn ws_upgrade(ws: WebSocketUpgrade) -> impl IntoResponse {
    ws.on_upgrade(handle_socket)
}

async fn handle_socket(client_ws: WebSocket) {
    let upstream_url = Client::from_env().ws_url();
    tracing::info!(%upstream_url, service = "market-data", "qdb ws proxy connecting");

    let (upstream, _) = match connect_async(&upstream_url).await {
        Ok(v) => v,
        Err(e) => {
            let (mut sink, _) = client_ws.split();
            let _ = sink
                .send(Message::Text(
                    format!(r#"{{"type":"error","message":"qdb connect failed: {e}"}}"#).into(),
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
