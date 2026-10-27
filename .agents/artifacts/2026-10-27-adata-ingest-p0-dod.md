# DoD：adata-ingest P0

- 日期：2026-10-27
- 级别：feature
- 关联：market schema adata 完整域 P0 采集
- 作者角色：Backend

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：`services/adata-ingest`（日历 + 指数/ETF/可转债 security + 种子日线）；东财 push2his 绕过 aarch64 MiniRacer；`map_index_exchange`；`ensure_security` 不降级 category；compose / prometheus / 边界文档 / `.env.example`
- 未做：P1–P3；全量指数/ETF 日线；错误 SZSE 影子 security 行清理（仅清了 adata bars）
- 已知风险：东财偶发断连需重试；同轮 meta 二次拉取可能空（限流）；`source_code=adata` 日线实际 HTTP 为东财
- 复验命令：

```bash
docker compose up -d --build adata-ingest
docker compose logs --tail 50 adata-ingest | grep round_done
docker compose exec -T postgres psql -U equitylab -d equitylab -c \
  "SELECT s.exchange_code,s.secu_code,s.secu_category,count(*) FROM market.bar_daily b JOIN market.security s ON s.inner_code=b.inner_code WHERE b.source_code='adata' GROUP BY 1,2,3 ORDER BY 3,1,2;"
docker compose exec -T adata-ingest python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9103/metrics').read().decode().split('equitylab_adata')[1][:200])"
python3 -m pytest packages/market-py/tests/test_symbols.py -q
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| 日历入库 | pass | calendar rows SSE/SZSE/BSE；security 有 index/etf/convertible |
| 指数日线 SSE:000001 等 | pass | adata bars：SSE 000001/000016/000300/000852 + SZSE 399001/399006 |
| ETF 种子日线 | pass | 8 只 ETF × ~119 根 |
| metrics :9103 | pass | `equitylab_adata_ingest_sync_total{...status="ok"}` |

## 冒烟（非仅 health）

| 命令 | 期望 | 实际 |
|---|---|---|
| round_done 日志 | index_bars>0 etf 或留存 ETF bars | index_bars=714；ETF 留存 8 标的 |
| bar_daily source=adata | 非空且指数挂正确交易所 | 14 组 exchange/code；无 SZSE:000001 脏 adata 行 |

## 文档

| 变更类型 | 已更新路径 |
|---|---|
| containers / 边界 / .env.example | `docs/platform/2026-10-15-containers.md`、`docs/market/2026-10-26-行情模块边界.md`、`.env.example` |

## 数据面

| 检查 | 结果 |
|---|---|
| adata-ingest rebuild | pass |
| 写路径有数据 | pass（calendar + security + bar_daily adata） |
| 热冷不串权 | pass（不写 qdb） |
