# DoD：adata-ingest P1 冷域写入

- 日期：2026-10-27
- 级别：feature
- 关联：docs/market/2026-10-27-market-schema-adata完整域.md §6 P1
- 作者角色：Backend

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：`equitylab_market.pg` P1 upsert；`adata-ingest` `p1_sync`（plate ths/east、plate_member、index_member、share_capital、industry_sw 容忍百度风控、dividend 东财优先→股数口径 adjust_factor）；compose/env/docs；容器 rebuild 冒烟
- 未做：P2 资金流/财务；现金除权因子（需 OHLC）；THS 概念成分全量接口（MiniRacer，已用按股 get_concept_ths 替代）；读 API/UI 展示板块成分
- 已知风险：百度 `getrelatedblock` 风控时申万为空；分红 adjust_factor 仅为送转股数口径；成分 `effective_from=1990-01-01` 快照幂等、不自动标记调出
- 复验命令：

```bash
docker compose up -d --build adata-ingest
docker compose exec -T \
  -e ADATA_INGEST_STOCK_CODES=600519,000001,300750 \
  -e ADATA_INGEST_STOCK_LIMIT=3 \
  -e ADATA_INGEST_INDEX_MEMBER_CODES=000300 \
  -e ADATA_INGEST_EAST_CONCEPT_CODES=BK0896 \
  adata-ingest python -c 'import adata,p1_sync; print(p1_sync.run_p1(adata))'
docker compose exec -T postgres psql -U equitylab -d equitylab -c \
  "SELECT 'plate' t,count(*) FROM market.plate UNION ALL
   SELECT 'plate_member',count(*) FROM market.plate_member UNION ALL
   SELECT 'index_member',count(*) FROM market.index_member UNION ALL
   SELECT 'share_capital',count(*) FROM market.share_capital UNION ALL
   SELECT 'dividend',count(*) FROM market.dividend;"
cd services/adata-ingest && python3 -m pytest test_dividend_parse.py -q
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| plate / plate_member 可写入 | pass | plate≥900；plate_member≥160；BK0896 成分 41 |
| index_member 种子指数 | pass | 000300 → 300 行 |
| share_capital 按股历史 | pass | 三票合计 164+ 行本轮；表内 882 |
| industry_sw 可写或优雅跳过 | pass* | 风控时 n=0 不崩；模块 `industry_sw.py` |
| dividend → adjust_factor | pass | 66 分红 / 21 送转因子 |
| 读路径零上游 | pass | 仅 adata-ingest 回源 |

## 冒烟（非仅 health）

| 命令 | 期望 | 实际 |
|---|---|---|
| `pytest test_dividend_parse.py` | 3 passed | 3 passed |
| 限量 `p1_sync` + PG count | plate/index/share/dividend 非空 | 见上 |
| `docker compose up -d --build adata-ingest` | recreate 成功 | ok |

## 文档

| 变更类型 | 已更新路径 |
|---|---|
| containers / 边界 / schema 完整域 / .env.example | `docs/platform/2026-10-15-containers.md`；`docs/market/2026-10-26-行情模块边界.md`；`docs/market/2026-10-27-market-schema-adata完整域.md`；`.env.example`；`docker-compose.yml` |

## 数据面

| 检查 | 结果 |
|---|---|
| adata-ingest rebuild/recreate | pass |
| 写路径有数据 | pass（上表） |
| 读路径未接上游 | pass |
