# DoD：币安现货热冷分离

- 日期：2026-10-30
- 级别：feature
- 关联：plan binance_hot-cold_split；`docs/market/2026-10-30-binance-热冷分离.md`
- 作者角色：Backend / DevOps

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：迁移扩 `bar_minute` 全周期+精度；`market-py` upsert/list BINANCE；collector 闭合棒写 PG + 启动即并行 PG 翻页回补（不阻塞于 cn_equity）；market-data `pg_binance` 合并读；边界/api/containers/索引/`.env.example` 对齐；BTCUSDT 冒烟深历史+左滑。
- 未做（须诚实）：RWA/代币化美股冷库；全 watchlist×全周期冷回补为异步长任务（启动后持续翻页）。
- 已知风险：`.env` 若设 `BINANCE_KLINE_BACKFILL=0` 则冷库浅；PG 未就绪时 klines 短暂回落 docs（非权威）。
- 复验命令：

```bash
docker compose exec -T postgres psql -U equitylab -c \
  "SELECT count(*) FROM market.bar_minute bm JOIN market.security s USING(inner_code) WHERE s.exchange_code='BINANCE' AND period='15m'"
curl -s 'http://localhost:3000/api/market/binance/klines?symbol=BTCUSDT&interval=15m&limit=500' | jq 'length'
# 左滑：用返回首根 openTime-1 再请求，期望 length>0
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| `market.bar_*` 有 BINANCE 行 | pass | `15m` count=7684（BTCUSDT 回补后） |
| klines limit=500 明显大于旧 docs 180 | pass | `length=500` |
| 左滑 endTime 有更早棒 | pass | `left_scroll=100`，末根 open < 主窗 oldest |
| snapshots 仍活 | pass | `BINANCE:BTCUSDT` price 非空 |

## 冒烟（非仅 health）

| 命令 | 期望 | 实际 |
|---|---|---|
| PG count 15m BINANCE | >180 | 7684 |
| BFF klines limit=500 | ≥400 | 500 |
| endTime=oldest-1 limit=100 | >0 且更早 | 100 |

## 文档

| 变更类型 | 已更新路径 | 跳过理由 |
|---|---|---|
| api / containers / 边界 / 专题 / 索引 / .env.example | `docs/platform/2026-10-15-api.md`、`containers.md`、`docs/market/2026-10-26-行情模块边界.md`、`2026-10-30-binance-热冷分离.md`、`2026-10-16-binance-market.md`、`docs/2026-10-26-文档索引.md`、`.env.example` | — |

## 数据面

| 检查 | 结果 | 证据 |
|---|---|---|
| collector / market-data rebuild | pass | compose up --build；pg pool ready |
| 写路径有数据 | pass | upsert + PG count |
| 读路径 API | pass | `/api/market/binance/klines` |
| 展示集 ⊆ 采集 | pass | 现货 watchlist 仍 collector BINANCE_SYMBOLS |
| 无 BINANCE 混入 cn-equity | pass | 未改 cn-equity |
| 非 skip 完成态 | pass | BACKFILL=1；quotes 开 |

## 运行态

- [x] 改动服务已 `--build` / recreate 后再验
- [x] 未把宿主机未重建改动当成线上绿

## 结论

- DoD：pass
- 可否进入 Review / Deploy：是
- 阻断原因：—
