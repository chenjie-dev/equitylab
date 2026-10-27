# DoD：adata-ingest P2 资金流 / 财务核心

- 日期：2026-10-27
- 级别：feature
- 关联：docs/market/2026-10-27-market-schema-adata完整域.md §6 P2
- 作者角色：Backend

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：`capital_flow_daily` / `capital_flow_plate_daily` / `finance_core` 写入；东财资金流直调（带 Referer）；`p2_sync` 挂入主轮；compose/env/docs；rebuild 冒烟
- 未做：P3 舆情；分时资金流（故意不进 market）；读 API/UI；全市场股票资金流回填
- 已知风险：push2his 资金流偶发断连（重试+UA）；板块资金流为当日快照非历史序列；`finance_core` 指标名为英文码为主
- 复验命令：

```bash
docker compose up -d --build adata-ingest
docker compose exec -T \
  -e ADATA_INGEST_STOCK_CODES=600519,000001,300750 \
  -e ADATA_INGEST_P2_STOCK_LIMIT=3 \
  adata-ingest python -c 'import adata,p2_sync; print(p2_sync.run_p2(adata))'
docker compose exec -T postgres psql -U equitylab -d equitylab -c \
  "SELECT 'cf' t,count(*) FROM market.capital_flow_daily UNION ALL
   SELECT 'plate_cf',count(*) FROM market.capital_flow_plate_daily UNION ALL
   SELECT 'fin',count(*) FROM market.finance_core;"
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| capital_flow_daily 可写 | pass | 冒烟 ≥32 行 |
| capital_flow_plate_daily 可写 | pass | 516 概念快照 |
| finance_core 长表可写 | pass | 396 指标行（3 票×4 报告期） |
| 读路径零上游 | pass | 仅 adata-ingest |

## 冒烟

| 命令 | 期望 | 实际 |
|---|---|---|
| 限量 `p2_sync.run_p2` | 三表非空 | cf 32 / plate 516 / fin 396 |
| rebuild adata-ingest | 成功 | ok |
