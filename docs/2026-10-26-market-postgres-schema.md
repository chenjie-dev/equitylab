# 历史行情 PostgreSQL 域模型（聚源语义对齐）

> 创建日：2026-10-26。配套 SQL：[`infra/postgres/migrations/20261026_market_schema.sql`](../infra/postgres/migrations/20261026_market_schema.sql)、[`infra/postgres/init.sql`](../infra/postgres/init.sql)。

## 1. 目标

- 历史 K 线、复权因子、交易日历、停牌落 **Postgres `market` schema**。
- 语义对齐聚源常用表：`SecuMain` / `QT_DailyQuote` / `QT_AdjustingFactor` / `QT_TradingDayNew` / `QT_Suspend`。
- **新浪 / adata 等只是 `data_source`**；业务 API 与路由用 **中国 A 股市场段** 名 `cn-equity`，不出现 ashare/adata 作资源名。

## 2. 与 qdb 的边界

| 层 | 职责 |
|---|---|
| **qdb** | 盘中快照、未闭合棒、订阅、短窗引擎 K 线（热路径） |
| **Postgres `market`** | 已闭合历史棒、日历、停牌、复权因子（冷/回测/翻历史） |

```text
上游（sina / binance / …）
  → collector（唯一回源）
      → qdb（quotes / trades / docs）
      → Postgres market.*（history bars / calendar / suspend）
  → research `/cn-equity`：history 优先 PG，realtime 仍 qdb，merged 拼接
```

## 3. 聚源对照

| 本项目表 | 聚源对照 | 说明 |
|---|---|---|
| `market.security` | SecuMain | `inner_code` 代理主键；`secu_code`+交易所唯一 |
| `market.bar_daily` | QT_DailyQuote | 日线；`trading_day` 为交易所日历日 |
| `market.bar_minute` | （分钟行情） | `bar_time` UTC；冗余 `trading_day` |
| `market.adjust_factor` | QT_AdjustingFactor | 只存因子，不存三份 OHLC |
| `market.trading_calendar` | QT_TradingDayNew | 按交易所 |
| `market.suspend` | QT_Suspend | 停牌区间 |
| `market.data_source` | （扩展） | `sina` / `binance` / `ondo` / `manual` |
| `market.ingest_watermark` | （运维） | 断点续爬 |

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

| 现状（废弃方向） | 目标 |
|---|---|
| `/ashare/*` | `/cn-equity/*` |
| `/api/ashare/*` | `/api/cn-equity/*` |
| `/markets/ashare` | `/markets/cn` |

旧路径可保留兼容代理一段时间。`meta.source` 可报 `sina` / `qdb` / `postgres`。

## 6. 写入与迁移

- **collector**：`services/collector/pg_market.py` 在 K 线回填时写 `bar_daily` / `bar_minute`、推进 `ingest_watermark`、粗填 `trading_calendar`；报价名含「停牌」时写 `suspend`。需 `DATABASE_URL`。
- **research**：`/cn-equity/klines` 历史优先读 PG，不足回落 qdb；盘中 realtime 仍 qdb。
- **新卷**：`init.sql` + `02_market_schema.sql` 挂载执行。
- **已有卷**：执行 `migrations/20261026_market_schema.sql`；可选将旧 `public.klines` 导入后 `DROP`。
- `public.klines` 标记废弃，新代码勿再写入。

## 7. 不做

财务报表、公告、股东名册、指数成分权重等——不建表。
