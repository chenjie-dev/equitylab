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
| GET | `/ashare/klines/{code}?k_type=1d&limit=` | K 线（前复权默认） |
| GET | `/ashare/five/{code}` | 五档 |
| GET | `/ashare/intraday/{code}` | 当日分时 |

`k_type`：`1d` / `1w` / `1M` / `5m` / `15m` / `30m` / `60m`（映射 adata `k_type`）。

## 冒烟

```bash
curl -s http://localhost:3000/api/research/ashare/ | head
curl -s 'http://localhost:3000/api/research/ashare/quotes?codes=600519,000001' | head -c 400
curl -s 'http://localhost:3000/api/research/ashare/klines/600519?k_type=1d&limit=5' | head -c 400
```

## 边界

- 多源公开爬虫/接口，可用性与字段以 adata 上游为准；非交易所官方低延迟 feed。
- K 线：优先 `adata.get_market`（东财）；若空/失败则回退新浪 `CN_MarketData.getKLineData`（容器内东财常 502）。
- 不做交易、账户、融资融券。
- 分钟 K 历史深度受上游限制（见 adata issues）。
