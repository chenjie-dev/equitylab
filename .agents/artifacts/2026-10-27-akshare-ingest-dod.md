# DoD：akshare 并行采集边车

- 日期：2026-10-27
- 级别：feature
- 关联：plan akshare并行采集边车；docs/market/2026-10-27-akshare-ingest.md
- 作者角色：Backend

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：`market.data_source=akshare` 迁移；`services/akshare-ingest`（P0–P3 + SKIP + `:9104` metrics）；compose / `.env.example`；边界/CONTEXT/文档索引；Prometheus scrape `akshare-ingest:9104`；rebuild 冒烟（日历/证券元数据/指数成分/北向/解禁/两融水位）
- 未做：产品路由/OpenAPI 含 akshare（故意不做）；写 qdb / 盘中报价；现金除权全量；分时资金/北向进 PG；首轮盘中东财限速下 stock/index/etf `bar_daily` 与 concept plate / hot_rank 多为 0（水位已记）
- 已知风险：东财上游易 `RemoteDisconnected`（P0 bars / P1 individual_info / hot）；`stock_margin_szse` 偶发列对齐失败（SSE/账户路径仍可写）；LHB 已按 `start_date`/`end_date` 修正，席位明细仍依赖上游稳定
- 复验命令：

```bash
docker compose up -d --build akshare-ingest
docker compose exec -T postgres psql -U equitylab -d equitylab -c \
  "SELECT code FROM market.data_source WHERE code='akshare';"
docker compose exec -T postgres psql -U equitylab -d equitylab -c \
  "SELECT dataset, detail FROM market.ingest_watermark WHERE source_code='akshare' ORDER BY dataset;"
docker compose exec -T postgres psql -U equitylab -d equitylab -c \
  "SELECT max(trading_day), count(*) FROM market.north_flow_daily WHERE source_code='akshare';"
# 可选：跳过 P1/P2 直打 P3
docker compose run --rm --no-deps \
  -e AKSHARE_INGEST_SKIP_P1=1 -e AKSHARE_INGEST_SKIP_P2=1 \
  akshare-ingest python -c 'import akshare as ak,p3_sync; print(p3_sync.sync_north(ak))'
curl -sf "http://127.0.0.1:3000/api/cn-equity/codes?limit=2" | head -c 200
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| `data_source` 有 akshare | pass | `code=akshare` |
| 水位 `source_code=akshare` 有 P0 记录 | pass | `calendar` n=8797；`security_stock` n=80；`p0_round` |
| 水位有 P3 记录 | pass | `north_flow_daily` / `lifting` / `margin_balance` / `p3_round` |
| 北向或行业相对推进或诚实空 | pass | 北向 `n=2775` `net_max=2026-10-26`（原 adata 近端停滞在 2024-08-16） |
| 读路径仍只 `/api/cn-equity/*` | pass | BFF `cn-equity/codes` HTTP 200；无 akshare BFF |
| 不写 qdb | pass | 边车仅 `equitylab_market.pg` |

## 冒烟（非仅 health）

| 命令 | 期望 | 实际 |
|---|---|---|
| `docker compose up -d --build akshare-ingest` | 镜像启动 | ok，metrics `:9104` |
| P0 日志 / 水位 | calendar + stock meta | `p0_done calendar=26391 stocks=80 … bars stock=0`（上游断连，诚实） |
| P3 `sync_north` | 行数>0 或 watermark note | **2775** / net_max **2026-10-26** |
| BFF cn-equity | 200 | `bff_cn_codes:200` |

## 文档

| 变更类型 | 已更新路径 | 跳过理由 |
|---|---|---|
| 边界 / CONTEXT / 索引 | `docs/market/2026-10-26-行情模块边界.md`、`CONTEXT.md`、`docs/2026-10-26-文档索引.md`、`docs/market/2026-10-27-akshare-ingest.md` | — |
| containers / .env.example | `docs/platform/2026-10-15-containers.md`、`.env.example` | — |
| api（产品路由） | — | 无新产品路由 |
| prometheus | `infra/observability/prometheus.yml` | — |

## 数据面

| 检查 | pass/fail | 证据 |
|---|---|---|
| akshare-ingest rebuild/recreate | pass | compose build + Started |
| 写路径有数据 | pass | north 2775；lifting/margin 200；security meta |
| 读路径 API 非空 | pass | `/api/cn-equity/codes` |
| 无产品名 akshare / ashare | pass | 仅 `data_source` |
| 环境非 skip 完成态 | pass | 默认 `AKSHARE_INGEST_SKIP=0`；轮次在跑 |

## 运行态

- [x] 改动服务已 `--build` / recreate 后再验
- [x] 未把宿主机未重建改动当成线上绿

## 结论

- DoD：pass
- 可否进入 Review / Deploy：是（feature；部署前建议确认东财连通与 `SLEEP_MS`）
- 阻断原因：无
