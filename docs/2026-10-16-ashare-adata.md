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
| GET | `/ashare/five/{code}` | 五档：优先 `ashare:depth:{EX}:{code}` docs；否则买一/卖一 |
| GET | `/ashare/intraday/{code}` | 分时（qdb 5m K 线合成；非逐笔） |

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

- 代码、报价、K 线、五档和分时都只读 `QDB_URL`（经 `equitylab_qdb`）。不在研究层回源。
- K 线 HTTP **窗口读**（`limit` / 可选 `endTime`，手册上限 5000）；勿一次拉全历史。
- 回源在 `services/collector`（新浪等公开源）：快照与 K 线写入 qdb（quotes 含 `bid_px`/`ask_px` 第 1 档）；五档写入 docs 键 `ashare:depth:{SSE\|SZSE\|BSE}:{code}`。代码需在 `QDB_FEED_CODES` / `COLLECTOR_CODES` 中（默认与 research `_SEED_CODES` 约 22 只对齐，含北交所如 `830879`；列表更长时扩 `.env`）。
- 北交所：qdb `BSE:6位码`（如 `BSE:830879` / `BSE:920088`），新浪 `bj` 前缀；`list_codes` 展示 `830879.BJ`。仍排除 BINANCE/ONDO。
- **启动**：A 股历史 trades 在首轮 live poll **之前**同步直写（qdb `late_tick`：早于未闭合桶的成交不进 K 线）。`bar_ts` 用北京时间。write_gate quotes 按标的只留最新。
- UI：`/markets/ashare` 为同花顺启发的左列表 / 右图+五档布局（红涨绿跌）。
- 非交易所官方低延迟 feed；实时合成非 Wind 终端授权数据。
- 不做交易、账户、融资融券。
- 分钟 K 历史深度受 collector 回填窗口限制。

## 排障：报价 / 快照一直空

1. 查 `.env`：`COLLECTOR_SKIP_ASHARE=1` 会关掉 A 股 REST 热路径与 backfill（compose 默认 `0`）。日常开发保持 `0` 或未设置。  
2. `docker logs equitylab-collector`：正常应见 `ashare=N (… rest hot-path)`；若是 `ashare=skip` / `ashare backfill skipped`，按上条改 env 后 `docker compose up -d --force-recreate collector`。  
3. 冒烟：`curl -s 'http://localhost:9090/v1/snapshots?symbols=SSE:600519'` 应有 `data`；再打 `GET /api/research/ashare/quotes?codes=600519`。  
4. 读路径无新浪：若 qdb 有数而 research 空，查 `QDB_URL` / 符号映射（`600519` → `SSE:600519`），勿在 research 回源。  
5. 报价对但日 K 几乎只有今天：日志须先有 `ashare backfill … blocking` / `ashare backfill done` 再 live tick；否则清空 `equitylab-qdbdata` 后重建 collector（见 containers 排障表）。
