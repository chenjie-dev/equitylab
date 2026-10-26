# DoD：history-ingest 冷日线回补

- **级别**：feature
- **日期**：2026-10-26

## 验收

| 条 | 证据 |
|---|---|
| 服务可启动并扫描 | `docker compose logs history-ingest` 含 `history-ingest cover=` / `fill=` |
| 写 PG 日线 | `docker exec equitylab-postgres psql -U equitylab -d equitylab -c "SELECT count(*) FROM market.bar_daily;"` |
| 文档边界 | `docs/market/2026-10-26-行情模块边界.md` §3.2b |

## 冒烟

```bash
docker compose up -d --build history-ingest
docker compose logs --tail=40 history-ingest
docker exec equitylab-postgres psql -U equitylab -d equitylab -c \
  "SELECT count(DISTINCT inner_code) FILTER (WHERE trading_day >= CURRENT_DATE - 180) AS codes_with_bars,
          count(*) FILTER (WHERE trading_day >= CURRENT_DATE - 180) AS bars_180d
   FROM market.bar_daily;"
```

已观测（2026-10-26）：`cover= universe=5579 gaps_queued=200`；`fill= SZSE:000035 … count=119 status=ok`。

## 已做 / 未做 / 风险 / 复验

- **已做**：独立 `history-ingest`；半年日线缺口扫描；限速；watermark fail/exhausted 退避；Compose/文档。
- **未做**：全市场分钟半年；复权因子权威源。
- **风险**：新浪限流/封禁；全表补齐需数小时；qdb 重建后须等 collector 写回 `cn-equity:codes`。
- **复验**：上表冒烟命令。
