# A 股公开行情（读 qdb）

> 创建日：2026-10-16。读路径只查 qdb；回源在 `services/collector`。本仓落点见 [2026-10-20-qdb-行情库.md](./2026-10-20-qdb-行情库.md)；**契约以同级 `../qdb/docs/manual/` 最新手册为准**，过时则先对齐再改本文。只读，无下单。

## 落点

| 层 | 路径 |
|---|---|
| Research | `GET /ashare/*`（`apps/research/app/ashare` + `qdb_client.py`） |
| Gateway | `/api/research/ashare/*` → 剥前缀到 Research |
| 前端 BFF | `/api/ashare/*` |
| UI | http://localhost:3001/markets/ashare |
| 写入 | `services/collector` → qdb `POST /v1/quotes` · `/v1/trades` |

研究层依赖 `QDB_URL`（compose 默认 `http://qdb:9090`）。不在读路径回源。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ashare/` | 能力目录 |
| GET | `/ashare/codes?q=&limit=` | 全市场代码（可搜） |
| GET | `/ashare/quotes?codes=000001,600519` | 批量实时行情 |
| GET | `/ashare/klines/{code}?k_type=1d&view=merged&limit=` | K 线（Wind 风格拆分，见下） |
| GET | `/ashare/five/{code}` | 五档（由 qdb 快照合成） |
| GET | `/ashare/intraday/{code}` | 当日分时（由 qdb K 线合成） |

`k_type`：`1d` / `1w` / `1M` / `5m` / `15m` / `30m` / `60m`（映射 qdb 周期或读路径折叠）。

### K 线：历史 vs 实时（对齐 Wind）

| 概念 | Wind | EquityLab | 说明 |
|---|---|---|---|
| 历史序列 | WSD | `history` | 仅**已完成** bar；盘中不含当日未收盘日 K |
| 实时快照 | WSQ | `realtime`（日/周/月） | 从 qdb `GET /v1/snapshots` 读；由 collector 写入 |
| 分钟未完成 | WSI 末根 | `realtime`（分钟） | 序列末根标 `bar_kind=realtime`，已完成分钟进 history |
| 合图 | WSD+WSQ | `merged` / `data`（默认） | 图表用；`view=history\|realtime\|merged` |

响应额外字段：`session`（上海时区 `pre|trading|lunch|post|closed`）、`history`、`realtime`、`merged`；兼容字段 `data`/`count` 随 `view` 切换。

每根 candle 含 `bar_kind`: `history` | `realtime`。

## 冒烟

```bash
curl -s http://localhost:3000/api/research/ashare/ | head
curl -s 'http://localhost:3000/api/research/ashare/quotes?codes=600519,000001' | head -c 400
curl -s 'http://localhost:3000/api/research/ashare/klines/600519?k_type=1d&view=merged&limit=5' | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('session'), d['history']['count'], bool(d.get('realtime')), d['count'])"
curl -s 'http://localhost:3000/api/research/ashare/klines/600519?k_type=1d&view=history&limit=3' | head -c 500
```

## 边界

- 代码、报价、K 线、五档和分时都只读 `QDB_URL`。不在研究层回源。
- 回源在 `services/collector`（新浪等公开源）：快照与 K 线写入 qdb。代码需在 `QDB_FEED_CODES` / `COLLECTOR_CODES` 中。
- 非交易所官方低延迟 feed；实时合成非 Wind 终端授权数据。
- 不做交易、账户、融资融券。
- 分钟 K 历史深度受 collector 回填窗口限制。
