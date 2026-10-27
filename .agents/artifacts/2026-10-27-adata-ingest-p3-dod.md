# DoD：adata-ingest P3 舆情日终冷写入

- 日期：2026-10-27
- 级别：feature
- 关联：docs/market/2026-10-27-market-schema-adata完整域.md §6 P3
- 作者角色：Backend

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：`lifting` / `margin_balance` / `north_flow_daily` / `lhb_list`+`lhb_detail` / `hot_rank_daily`；解禁与北向东财直调；`p3_sync` 入主轮；docs/compose；rebuild 冒烟
- 未做：舆情读 API/UI；分时北向/热度（故意不进 market）
- 已知风险：东财北向 `NET_DEAL_AMT` 近端常 null → `north_flow_daily` 可能为 0；`pop_rank_100_east` 偶发断连（有重试）；THS 解禁原接口依赖 MiniRacer（已绕开）
- 复验命令：

```bash
docker compose up -d --build adata-ingest
docker compose exec -T \
  -e ADATA_INGEST_LHB_DATES=2026-10-23 \
  -e ADATA_INGEST_LIFTING_PAGES=3 \
  adata-ingest python -c 'import adata,p3_sync; print(p3_sync.run_p3(adata))'
docker compose exec -T postgres psql -U equitylab -d equitylab -c \
  "SELECT 'lifting' t,count(*) FROM market.lifting UNION ALL
   SELECT 'margin',count(*) FROM market.margin_balance UNION ALL
   SELECT 'lhb',count(*) FROM market.lhb_list UNION ALL
   SELECT 'hot',count(*) FROM market.hot_rank_daily;"
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| lifting 可写 | pass | 150 |
| margin_balance 可写 | pass | 16 |
| lhb 可写 | pass | list 101 / detail≥37 |
| hot_rank 可写 | pass | 120（ths 100+概念 20） |
| north 优雅降级 | pass | n=0 + watermark note |

## 冒烟

| 命令 | 期望 | 实际 |
|---|---|---|
| 限量 `p3_sync.run_p3` | 解禁/两融/龙虎/热度非空 | 见上 |
| rebuild | 成功 | ok |
