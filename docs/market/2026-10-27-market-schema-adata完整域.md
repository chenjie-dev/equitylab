# market schema：adata 完整冷域

> 创建日：2026-10-27。在既有聚源对齐表之上，按 [adata](https://github.com/1nchaos/adata) **可冷落**能力扩展 Postgres `market`。  
> 模块禁令：[行情模块边界](./2026-10-26-行情模块边界.md)。首版表结构：[market-postgres-schema](./2026-10-26-market-postgres-schema.md)。  
> SQL：[`infra/postgres/migrations/20261027_market_schema_adata.sql`](../infra/postgres/migrations/20261027_market_schema_adata.sql)。

## 1. 目标

- 支撑 cn-equity **完整行情业务冷数据**：证券主数据、板块/成分、日线、分红复权、资金流、核心财务、ETF/可转债、舆情日终。
- 语义继续对齐聚源常用表；供应商只进 `data_source` / `plate.vendor`，**不做**产品路由名。
- **本轮只落库表与文档**；adata 写入采集分 P0–P3 另开（见 §6）。

## 2. 热冷边界

| 进 Postgres `market` | 进 qdb（不建 PG 权威表） |
|---|---|
| 已闭合日线、维度、成分、分红、日度资金流/财务/舆情快照 | 实时报价、五档、分笔、当日分时 K/资金流 |
| 交易日历、停牌 | WebSocket 会话状态 |

周/月 K：**不落物理表**，由 `bar_daily` 聚合。  
三大报表明细、公告原文、股东名册、通达信扫雷全文：**不建表**。

价格约定：库内只存**未复权原始价**；若上游只给复权价，默认拒写，水位 `detail.quality=adjusted_upstream`。

## 3. adata API ↔ 表 ↔ 聚源

### 3.1 基本信息

| adata API | 本项目表 | 聚源近似 |
|---|---|---|
| `stock.info.all_code` | `security`（category=`stock`） | SecuMain |
| `stock.info.all_index_code` | `security`（category=`index`） | SecuMain |
| `fund.info.all_etf_exchange_traded_info` | `security`（category=`etf`） | SecuMain |
| `bond.info.all_convert_code` | `security`（category=`convertible`） | SecuMain |
| `stock.info.get_stock_shares` | `share_capital` | LC_ShareStru |
| `stock.info.get_industry_sw` | `industry_sw` + `security_industry` | LC_ExgIndustry |
| `stock.info.all_concept_code_ths` / `_east` | `plate`（vendor=`ths`/`east`） | 概念板块 |
| `stock.info.concept_constituent_*` / `get_concept_*` / `get_plate_east` | `plate_member` | 概念成分 |
| `stock.info.index_constituent` | `index_member` | LC_IndexComponent |
| `stock.info.trade_calendar` | `trading_calendar` | QT_TradingDayNew |

### 3.2 行情（冷）

| adata API | 本项目表 | 聚源近似 |
|---|---|---|
| `stock.market.get_market`（日） | `bar_daily` | QT_DailyQuote |
| `get_market_index` / `get_market_concept_*` / `get_market_etf`（日） | `bar_daily`（对应 security） | 同上 |
| `get_dividend` | `dividend` → 可选推 `adjust_factor` | 分红 / QT_AdjustingFactor |
| `get_capital_flow` | `capital_flow_daily` | （扩展） |
| `all_capital_flow_east` | `capital_flow_plate_daily` | （扩展） |
| `stock.finance.get_core_index` | `finance_core` | 核心指标摘要 |

实时类（`list_market_current` / `get_market_five` / `get_market_bar` / `*_min` / `*_current`）→ **qdb**。

### 3.3 舆情（日终冷表）

| adata API | 本项目表 |
|---|---|
| `sentiment.stock_lifting_last_month` | `lifting` |
| `sentiment.securities_margin` | `margin_balance` |
| `sentiment.north.north_flow` | `north_flow_daily` |
| `sentiment.hot.list_a_list_daily` / `get_a_list_info` | `lhb_list` / `lhb_detail` |
| `pop_rank_100_east` / `hot_rank_100_ths` / `hot_concept_20_ths` | `hot_rank_daily` |

北向/热度**当日分时**仍走 qdb 或短期缓存，不进冷权威。

## 4. 表字典

**列级注释 SSOT**：以 SQL `COMMENT ON` 为准（[`20261027_market_schema_adata.sql`](../infra/postgres/migrations/20261027_market_schema_adata.sql)）。下文为结构摘要；查库可用 `\d+ market.<table>`。

### 4.1 扩展既有

| 对象 | 变更 |
|---|---|
| `exchange` | 增伪交易所 `THS` / `EAST`（概念码隔离） |
| `data_source` | 增 `adata` / `eastmoney` / `ths` |
| `security.secu_category` | 约定：`stock\|index\|concept\|etf\|convertible\|other`（CHECK） |
| `security.vendor_code` | 可选；同花顺等重编码 |

`bar_daily` / `bar_minute` / `adjust_factor` / `trading_calendar` / `suspend` / `ingest_watermark`：**沿用**。指数/概念/ETF 日线共用 `bar_daily`。

### 4.2 主数据 / 板块

| 表 | PK | 要点 |
|---|---|---|
| `share_capital` | `(inner_code, change_date)` | 总股本、流通股本（股） |
| `industry_sw` | `industry_code` | `level` 1/2；`parent_code` |
| `security_industry` | `(inner_code, industry_code, effective_from)` | 申万归属 |
| `plate` | `(vendor, plate_code)` | `vendor`∈`ths\|east`；`plate_kind`∈`concept\|industry\|region\|other`；可选 `inner_code` 链到 category=concept 的 security 以便写 bar_daily |
| `plate_member` | `(vendor, plate_code, inner_code, effective_from)` | `effective_to` 可空 |
| `index_member` | `(index_inner_code, member_inner_code, effective_from)` | 官方指数成分 |

### 4.3 公司行动

| 表 | PK | 要点 |
|---|---|---|
| `dividend` | `id` BIGSERIAL；唯一 `(inner_code, ex_date, announce_date)` | 派息/送股/转增等 NUMERIC；`source_code` |

### 4.4 资金 / 财务

| 表 | PK | 要点 |
|---|---|---|
| `capital_flow_daily` | `(inner_code, trading_day)` | 主力/超大/大/中/小净流入（元） |
| `capital_flow_plate_daily` | `(vendor, plate_code, trading_day)` | 概念板块资金流 |
| `finance_core` | `(inner_code, report_date, indicator_code)` | 筛选用指标；value NUMERIC + unit 可选 |

### 4.5 舆情

| 表 | PK | 要点 |
|---|---|---|
| `lifting` | `(inner_code, lift_date, id)` 或 `id` + UNIQUE | 解禁量/占比 |
| `margin_balance` | `(trading_day, market_scope)` | 两融余额 |
| `north_flow_daily` | `(trading_day)` | 北向净流入 |
| `lhb_list` | `id`；UNIQUE `(trading_day, inner_code, list_reason)` | 龙虎榜日列表 |
| `lhb_detail` | `id`；FK `lhb_list_id` | 席位买卖 |
| `hot_rank_daily` | `(trading_day, vendor, rank_type, rank_no)` | 人气/热股/热概念快照 |

## 5. 伪交易所与概念行情

概念本身无 SSE/SZSE 席位：用 `exchange_code`=`THS`|`EAST`，`secu_category`=`concept`，`secu_code`=厂商板块码（如 `BK0800` / 同花顺概念码）。  
`plate.inner_code`（可空）指向该 security，便于 `bar_daily` 与板块行情共用一套 K 线表。

## 6. 采集优先级

1. **P0（已落地 `services/adata-ingest`）**：日历权威 + 指数/ETF/可转债 `security` + 种子日线（`ADATA_INGEST_*`）  
2. **P1（已落地同进程 `p1_sync`）**：`plate`（ths 目录 + east push2）/ `plate_member`（按股概念 + 种子 east 成分）/ `index_member` / `share_capital` / `industry_*`（百度申万；风控时跳过）/ `dividend`（东财 RPT_SHAREBONUS_DET 优先，adata 百度回落）→股数口径 `adjust_factor`；`ADATA_INGEST_SKIP_P1=1` 可关  
3. **P2（未做）**：`capital_flow_*` / `finance_core`  
4. **P3（未做）**：舆情冷表日终 job  

写者仍仅采集族；读路径零上游。

## 7. 迁移与挂载

- 已有卷：执行 `migrations/20261027_market_schema_adata.sql`  
- 新卷：compose 挂载为 `03_market_schema_adata.sql`（在 `02_market_schema.sql` 之后）  
- `ingest_watermark.dataset` 建议值：`share_capital`、`plate_member`、`index_member`、`dividend`、`capital_flow_daily`、`finance_core`、`lifting`、`lhb_list`、`hot_rank_daily`、`north_flow_daily`、`margin_balance` 等
