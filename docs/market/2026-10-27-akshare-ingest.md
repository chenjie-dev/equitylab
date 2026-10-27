# akshare-ingest（并行冷采集）

> 创建日：2026-10-27。边车 `services/akshare-ingest`：经 [akshare](https://github.com/akfamily/akshare) 向**既有** Postgres `market` 灌数。  
> 模块禁令：[行情模块边界](./2026-10-26-行情模块边界.md)。产品读面仍是 cn-equity。

## 0. 不变量（源头 vs 库）

- **本系统表结构优先**：`market.*` / qdb 数据模型不因 akshare 而改；禁止为 SDK 加专用表/列或改主键。
- **允许的库变更**：仅 `market.data_source` 多一行 `akshare`（及行级 `source_code` / 分源水位）。
- **写入路径**：只走 `equitylab_market.pg` upsert → 与 sina/adata **同表**；热域 qdb 仍由 collector 等既有写路径负责，本边车不另起 qdb schema。
- **P0–P3**：实现分期标签，对应的是「填哪些已有表」，不是「设计新表」。

## 1. 职责

| 做 | 不做 |
|---|---|
| 授权回源 → 既有 `market.*`，`source_code=akshare` | 改库表设计；为源分叉 schema |
| P0–P3 与 adata-ingest **并行灌同一套表** | 写 qdb / 盘中报价（热域另册） |
| 日线仅未复权（`adjust=""`） | OpenAPI / BFF / 路由名含 `akshare` |
| | 读路径回源 |

水位按 `source_code` 分列，与 adata/sina **互不覆盖**；同表行靠 upsert `COALESCE` 合并。

## 2. 阶段 ↔ 既有表 ↔ 接口（实现侧以代码为准）

| 阶段 | 写入的既有表（不新建） | 典型 akshare 接口 |
|---|---|---|
| P0 | `trading_calendar`、`security`、`bar_daily` | `tool_trade_date_hist_sina`；`stock_info_a_code_name`；`stock_zh_a_hist`；指数/ETF 日线 |
| P1 | `plate`/`plate_member`、`index_member`、`share_capital`、`industry_*`、`dividend` | `stock_board_concept_*_em`；`index_stock_cons`；`stock_individual_info_em`；行业板成分 |
| P2 | `capital_flow_*`、`finance_core` | `stock_individual_fund_flow`；`stock_fund_flow_concept`；`stock_financial_analysis_indicator` |
| P3 | `lifting`、`margin_balance`、`north_flow_daily`、`lhb_*`、`hot_rank_daily` | 解禁/两融；**`stock_hsgt_hist_em` 北向**；龙虎榜；人气榜 |

## 3. 运行

```bash
# 已有 PG 卷：登记 data_source
docker compose exec -T postgres psql -U equitylab -d equitylab \
  -f /docker-entrypoint-initdb.d/04_market_data_source_akshare.sql
# 或宿主机：
# psql "$DATABASE_URL" -f infra/postgres/migrations/20261027_market_data_source_akshare.sql

docker compose up -d --build akshare-ingest
docker compose logs -f akshare-ingest
```

环境变量见 `.env.example`（`AKSHARE_INGEST_*`）；指标默认 `:9104/metrics`。  
`AKSHARE_INGEST_SKIP=1` 空转；`SKIP_P1/P2/P3` 关阶段。

## 4. 与 adata-ingest

- 独立镜像与限速，避免 SDK 互相拖死。  
- 北向/行业等 adata 弱项可由本边车补写；读面不感知供应商。  
- 对账：`SELECT source_code, dataset, count(*) FROM market.ingest_watermark GROUP BY 1,2`。
