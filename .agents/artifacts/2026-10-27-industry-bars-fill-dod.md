# DoD：行业归属灌数 + akshare 日线加固

- 日期：2026-10-27
- 级别：feature
- 关联：plan 行业归属与日线加固
- 作者角色：Backend / Data

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：akshare 行业板优先灌数（去宇宙过滤、板默认 80）；板不可达时 **EM2016 F10 回落**；`SLEEP_MS` 默认 800 + `call_ak` 断连重试；adata `INDUSTRY_STOCK_LIMIT`（默认 400）；`list_securities` 沪深优先；文档 / compose / `.env.example`
- 未做：东财行业板 push2 在本环境仍不可达（已诚实回落 EM2016）；akshare `bar_daily` 种子因上游断连仍为 0（重试与 `note=upstream_disconnect` 水位已就位）
- 已知风险：push2 / `stock_zh_a_hist` 易断连；坏代理会加剧失败；全市场日线仍靠 sina/`history-ingest`
- 复验命令：

```bash
docker compose up -d --build akshare-ingest adata-ingest
docker compose run --rm --no-deps \
  -e AKSHARE_INGEST_INDUSTRY_EM2016_LIMIT=180 \
  akshare-ingest python -c 'import akshare as ak,p1_sync; print(p1_sync.sync_industry(ak, []))'
docker compose exec -T postgres psql -U equitylab -d equitylab -c \
  "SELECT count(*) FROM market.security_industry; SELECT source_code,count(*) FROM market.security_industry GROUP BY 1;"
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| `security_industry` ≥500 或板成员量级 | pass | **563**（akshare 540 + adata 23） |
| `industry_sw` 码表扩容 | pass | **203**（原 23） |
| 不改 schema | pass | 仅 upsert 既有表 |
| 日线韧性（重试/限速） | pass（能力） | `CALL_RETRIES`/`SLEEP_MS=800`；冒烟 bars=0 诚实 |
| 读路径仍 cn-equity | pass | BFF codes 可用 |

## 冒烟

| 命令 | 期望 | 实际 |
|---|---|---|
| akshare `sync_industry` | members 大幅上升 | boards=0 → em2016=**540** |
| `bar_daily` source=akshare | >0 或 watermark note | **0** + 断连重试日志 / disconnect 水位路径 |
| rebuild sidecars | 成功 | ok |

## 文档

| 路径 | 说明 |
|---|---|
| `docs/market/2026-10-27-akshare-ingest.md` | 行业/限速/EM2016 |
| `docs/market/2026-10-26-行情模块边界.md` | §3.2c/d |
| `docs/market/2026-10-27-market-schema-adata完整域.md` | INDUSTRY_STOCK_LIMIT |
| `.env.example` / `docker-compose.yml` | 新 env |

## 结论

- DoD：pass（行业主目标达成；日线加固已交付，上游仍拒写属已知风险）
- 可否进入 Review：是
