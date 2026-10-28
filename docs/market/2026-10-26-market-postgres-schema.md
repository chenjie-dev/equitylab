# 历史行情 PostgreSQL 域模型（聚源语义对齐）

> 创建日：2026-10-26。配套 SQL：[`infra/postgres/migrations/20261026_market_schema.sql`](../infra/postgres/migrations/20261026_market_schema.sql)、[`infra/postgres/init.sql`](../infra/postgres/init.sql)。  
> **模块职责与禁令**以 [行情模块边界](./2026-10-26-行情模块边界.md) 为准；本文只定义 **冷库表结构**。

## 1. 目标

- 历史 K 线、复权因子、交易日历、停牌落 **Postgres `market` schema**（冷权威）。
- 语义对齐聚源常用表：`SecuMain` / `QT_DailyQuote` / `QT_AdjustingFactor` / `QT_TradingDayNew` / `QT_Suspend`。
- **新浪 / adata 等只是 `data_source`**；业务 API 与路由用 **中国 A 股市场段** 名 `cn-equity`，不出现 ashare/adata 作资源名。adata 库参考：<https://github.com/1nchaos/adata>。
- **adata 完整冷域**（板块/成分/资金流/财务/舆情等）见 **[2026-10-27-market-schema-adata完整域](./2026-10-27-market-schema-adata完整域.md)** 与迁移 `20261027_market_schema_adata.sql`。本文保留 **首版基线** 说明。

## 2. 本 schema 边界

| 属于 `market` | 不属于 `market` |
|---|---|
| 已闭合 `bar_daily` / `bar_minute` | 盘中未闭合棒、WebSocket 会话（→ qdb） |
| `adjust_factor` / `trading_calendar` / `suspend` | 币安/RWA 盘中流（→ qdb；读经 market-data） |
| `security` / `data_source` / `ingest_watermark` | 研报向量、会话审计（其它表/库） |
| 板块/成分/股本/行业/分红/资金流/财务/舆情冷表 | 三大报明细、公告原文、当日分时（见完整域文） |

写入默认 **仅 collector**；读取 A 股历史经 **research `/cn-equity`**。详见 [模块边界 §3.4](./2026-10-26-行情模块边界.md)。

## 3. 聚源对照

| 本项目表 | 聚源对照 | 说明 |
|---|---|---|
| `market.security` | SecuMain | `inner_code` 代理主键；`secu_code`+交易所唯一 |
| `market.bar_daily` | QT_DailyQuote | 日线；`trading_day` 为交易所日历日 |
| `market.bar_minute` | （分钟行情） | `bar_time` UTC；冗余 `trading_day` |
| `market.adjust_factor` | QT_AdjustingFactor | 只存因子，不存三份 OHLC |
| `market.trading_calendar` | QT_TradingDayNew | 按交易所 |
| `market.suspend` | QT_Suspend | 停牌区间 |
| `market.data_source` | （扩展） | `sina` / `adata` / `eastmoney` / `ths` / `binance` / … |
| `market.ingest_watermark` | （运维） | 断点续爬 |
| 板块/成分/资金/财务/舆情等 | 见完整域文 | 迁移 `20261027_*` |

价格：交易所**原始价** `NUMERIC`（元）。成交量：股。成交额：元。  
复权：读路径按 `adjust_type` 用因子变换；**库内不存复权价行**。

周/月 K：**不落物理表**，由日线聚合。

## 4. 表字典（摘要）

详见 SQL COMMENT。要点：

- `security.inner_code`：全域代理键（对齐 InnerCode 用法）。
- `bar_daily` PK `(inner_code, trading_day)`。
- `bar_minute` PK `(inner_code, period, bar_time)`；`period` ∈ `1m|5m|15m|60m`。首版未按月分区；后续可 `PARTITION BY RANGE (bar_time)`。
- `trading_calendar` PK `(exchange_code, calendar_date)`。
- `suspend`：`inner_code` + `suspend_from` 唯一。

## 5. API 命名

| 路径 | 说明 |
|---|---|
| `/cn-equity/*` | Research 产品面 |
| `/api/cn-equity/*` | BFF / Gateway |
| `/markets/cn` | 前端 |

旧 `ashare` 路径已删除。`meta.source` 可报 `sina` / `qdb` / `postgres`。

## 6. 写入与迁移

- **collector / history-ingest**：经 `packages/market-py`（`equitylab_market.pg` / `.sina`）写 `bar_*`、水位、日历；history-ingest 持续扫日线缺口。
- **交易日历权威**：[pandas_market_calendars](https://github.com/rsheftel/pandas_market_calendars)（`data_source=pmc`），由 `adata-ingest` 调用 `equitylab_market.pmc_calendar` 以 `mode=replace` 写 **今年 + 明年**。库内用日历名 **`SSE`** 覆盖 SSE/SZSE/BSE（A 股休市一致；勿用库的 `BSE`=孟买）。明年若会话≈纯工作日则跳过 replace，改 seed-insert。`akshare-ingest` 默认**不** replace（`AKSHARE_CALENDAR_REPLACE=1` 才应急回退）。collector `seed_calendar_weekdays` 仅为 **insert 占位**。写入后窗口函数回填 `prev`/`next`。
- **research**：`/cn-equity/klines` 历史优先读 PG，不足回落 qdb；盘中 realtime 仍 qdb。
- **新卷**：`init.sql` + `02_market_schema.sql` 挂载执行。
- **已有卷**：执行 `migrations/20261026_market_schema.sql`；可选将旧 `public.klines` 导入后 `DROP`。
- `public.klines` 标记废弃，新代码勿再写入。

## 7. 不做 / 后置

- **不做 PG 权威表**：盘中五档/分笔/当日分时、三大报表明细、公告原文、股东名册、通达信扫雷全文、周月 K 物理表。  
- **完整域已建表、采集后置**：成分/板块/资金流/核心财务/舆情日终等见 [adata 完整域](./2026-10-27-market-schema-adata完整域.md) §6（P0–P3）。指数成分 `weight` 可空（adata 常无权重）。
