# A 股公开行情（adata）

> 创建日：2026-10-16。研究层封装 [1nchaos/adata](https://github.com/1nchaos/adata)；只读，无下单。

## 落点

| 层 | 路径 |
|---|---|
| Research | `GET /ashare/*`（`apps/research/app/ashare` + `routers/ashare.py`） |
| Gateway | `/api/research/ashare/*` → 剥前缀到 Research |
| 前端 BFF | `/api/ashare/*` |
| UI | http://localhost:3001/markets/ashare |

依赖：`requirements.txt` 中 `adata` + `pandas`。同步 adata 调用经 `asyncio.to_thread`，代码列表 TTL≈1h，报价 TTL≈5s。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/ashare/` | 能力目录 |
| GET | `/ashare/codes?q=&limit=` | 全市场代码（可搜） |
| GET | `/ashare/quotes?codes=000001,600519` | 批量实时行情 |
| GET | `/ashare/klines/{code}?k_type=1d&view=merged&limit=` | K 线（Wind 风格拆分，见下） |
| GET | `/ashare/five/{code}` | 五档 |
| GET | `/ashare/intraday/{code}` | 当日分时 |

`k_type`：`1d` / `1w` / `1M` / `5m` / `15m` / `30m` / `60m`（映射 adata `k_type`）。

### K 线：历史 vs 实时（对齐 Wind）

| 概念 | Wind | EquityLab | 说明 |
|---|---|---|---|
| 历史序列 | WSD | `history` | 仅**已完成** bar；盘中不含当日未收盘日 K |
| 实时快照 | WSQ | `realtime`（日/周/月） | 新浪 `hq.sinajs.cn` 开高低现量 → 合成当日未完成 bar |
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

- 多源公开爬虫/接口，可用性与字段以 adata 上游为准；非交易所官方低延迟 feed。
- K 线：优先 `adata.get_market`（东财）；若空/失败则回退新浪 `CN_MarketData.getKLineData`（容器内东财常 502）。
- 实时合成依赖新浪公开快照，非 Wind 终端授权数据。
- 不做交易、账户、融资融券。
- 分钟 K 历史深度受上游限制（见 adata issues）。
