//! 币安公开 WebSocket 代理。

use super::client::Client;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Query, State,
    },
    response::IntoResponse,
};
use futures_util::{SinkExt, StreamExt};
use serde::Deserialize;
use std::sync::Arc;
use tokio_tungstenite::{connect_async, tungstenite::Message as TMessage};

#[derive(Deserialize, Default)]
pub struct WsQuery {
    #[serde(default)]
    streams: String,
    #[serde(default)]
    stream: String,
}

pub async fn ws_upgrade(
    ws: WebSocketUpgrade,
    State(client): State<Arc<Client>>,
    Query(q): Query<WsQuery>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_socket(socket, client, q))
}

async fn handle_socket(client_ws: WebSocket, client: Arc<Client>, q: WsQuery) {
    let upstream_url = match build_upstream_url(&client.ws_base, &q) {
        Ok(u) => u,
        Err(msg) => {
            let (mut sink, _) = client_ws.split();
            let _ = sink
                .send(Message::Text(format!(r#"{{"error":"{msg}"}}"#).into()))
                .await;
            let _ = sink.close().await;
            return;
        }
    };

    tracing::info!(
        %upstream_url,
        service = "market-data",
        exchange = "binance",
        "ws proxy connecting"
    );

    let (upstream, _) = match connect_async(&upstream_url).await {
        Ok(v) => v,
        Err(e) => {
            let (mut sink, _) = client_ws.split();
            let _ = sink
                .send(Message::Text(
                    format!(r#"{{"error":"upstream connect failed: {e}"}}"#).into(),
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

fn build_upstream_url(ws_base: &str, q: &WsQuery) -> Result<String, String> {
    let streams = q.streams.trim();
    let stream = q.stream.trim();
    if !streams.is_empty() {
        return Ok(format!(
            "{}/stream?streams={}",
            ws_base.trim_end_matches('/'),
            streams.to_lowercase()
        ));
    }
    if !stream.is_empty() {
        return Ok(format!(
            "{}/ws/{}",
            ws_base.trim_end_matches('/'),
            stream.to_lowercase()
        ));
    }
    Err("provide ?streams=btcusdt@trade/btcusdt@ticker or ?stream=btcusdt@trade".into())
}
