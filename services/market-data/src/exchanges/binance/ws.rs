//! 币安公开 WebSocket：读路径禁止回源。订阅读请用 `/qdb/ws`。

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

#[derive(Deserialize, Default)]
pub struct WsQuery {
    #[serde(default)]
    streams: String,
    #[serde(default)]
    stream: String,
}

pub async fn ws_upgrade(
    ws: WebSocketUpgrade,
    State(_client): State<Arc<Client>>,
    Query(q): Query<WsQuery>,
) -> impl IntoResponse {
    ws.on_upgrade(move |socket| handle_socket(socket, q))
}

async fn handle_socket(client_ws: WebSocket, q: WsQuery) {
    let _ = (&q.streams, &q.stream);
    let (mut sink, _) = client_ws.split();
    let _ = sink
        .send(Message::Text(
            r#"{"error":"qdb-only: refusing upstream Binance WS; use /qdb/ws (SELECT … SUBSCRIBE)"}"#
                .into(),
        ))
        .await;
    let _ = sink.close().await;
}
