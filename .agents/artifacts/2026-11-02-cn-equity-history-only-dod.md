# DoD：A 股历史-only + 多周期 K 线

- 日期：2026-11-02
- 级别：feature
- 关联：关掉 A 股盘中 qdb；history-ingest 日+5m/15m/60m
- 作者角色：Backend / Frontend

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：Compose 默认 `COLLECTOR_SKIP_CN_EQUITY=1`；`equitylab_market.cn_universe`；history-ingest 刷新 codes + 多周期分钟；research `view=history` 默认 + 60m→1h 存读对齐；`/markets/cn` 历史模式 UI；文档同步
- 未做：全市场分钟半年硬灌；1m 周期；恢复盘中五档产品能力
- 已知风险：分钟回补全宇宙较慢（seed 已优先）；启动期 codes 发布依赖 qdb 就绪（已短重试）
- 复验命令：

```bash
docker compose logs collector --tail 20 | rg cn_equity=skip
docker compose logs history-ingest --tail 40 | rg 'codes published|minute_periods|fill=15m SSE:600519'
curl -sS 'http://localhost:3000/api/cn-equity/klines/600519?k_type=5m&view=history&limit=30'
curl -sS 'http://localhost:3000/api/cn-equity/klines/600519?k_type=15m&view=history&limit=30'
curl -sS 'http://localhost:3000/api/cn-equity/klines/600519?k_type=60m&view=history&limit=30'
curl -sS 'http://localhost:3000/api/cn-equity/quotes?codes=600519'
docker compose exec -T postgres psql -U equitylab -d equitylab -c \
  "SELECT b.period, count(*) FROM market.bar_minute b JOIN market.security s ON s.inner_code=b.inner_code WHERE s.secu_code='600519' AND s.exchange_code='SSE' GROUP BY 1;"
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| collector 无 A 股热写 | pass | 日志 `cn_equity=skip` |
| 多周期入库 | pass | 600519：5m/15m/1h 均有行 |
| 读面 history | pass | klines 1d/5m/15m/60m → `source=postgres` |
| 列表价历史 | pass | quotes `postgres:bar_daily` + note |
| UI 构建 | pass | frontend image build 成功 |

## 冒烟

| 命令 | 期望 | 实际 |
|---|---|---|
| klines 5m/15m/60m | count>0 postgres | 29/29/29 postgres |
| quotes 600519 | bar_daily note | pass |
| codes doc | count≈数千 | 5579 |
