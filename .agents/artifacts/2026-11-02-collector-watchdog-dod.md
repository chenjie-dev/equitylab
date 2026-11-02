# DoD：collector 进程守护

- 日期：2026-11-02
- 级别：feature
- 关联：行情采集不稳 → qdb/WS/catalog/write_gate 探测与有限自愈
- 作者角色：Backend

## 已做 / 未做 / 已知风险 / 复验命令

- 已做：`watchdog.py`（/health:9105、探测、冷却自愈）；`feed_health_stats`；prom gauges；compose healthcheck + 端口；文档/`.env.example`；collector rebuild 冒烟绿
- 未做：Grafana 面板专页；对 compose 因 health 自动 recreate（仅标记 unhealthy）；A 股 REST 专用守护项
- 已知风险：全市场启动期 docs/quotes 积压会 `watchdog warn` 但不致 503；冷 WS SSL 偶发重连；自愈冷却 180s 内不重复动作
- 复验命令：

```bash
docker compose up -d --build collector
curl -sS http://localhost:9105/health
docker compose ps collector
curl -sS http://localhost:9101/metrics | rg equitylab_collector_watchdog
docker compose logs collector --tail 50 | rg watchdog
```

## 验收对照

| 验收标准 | 结果 | 证据 |
|---|---|---|
| `/health` 暴露综合状态 | pass | `curl localhost:9105/health` → HTTP 200，`ok:true`，含 qdb/catalog/ws/write_gate |
| Compose healthcheck 可用 | pass | `ps` → `healthy`，端口 `9105` |
| WS 分片可观测 | pass | health `hot_ok/cold_ok`；metrics `equitylab_binance_ws_shards` |
| 有限自愈入口存在 | pass | `qdb_recover_catalog_ws` / `restart_binance_ws` / `republish_catalog` + cooldown |

## 冒烟（非仅 health）

| 命令 | 期望 | 实际 |
|---|---|---|
| `curl :9105/health` | 200 + catalog count≈1373 | ok，count=1373，ws hot 1/1 cold≥半 |
| metrics watchdog_ok | 1 | `equitylab_collector_watchdog_ok 1.0` |
| collector recreate 含 watchdog.py | 镜像含模块 | Dockerfile COPY + 日志 `watchdog health :9105` |

## 文档

| 变更类型 | 已更新路径 |
|---|---|
| containers / .env.example / binance 全市场 | `docs/platform/2026-10-15-containers.md`、`.env.example`、`docs/market/2026-10-30-binance-全市场采集.md` |

## 数据面

| 检查 | 结果 |
|---|---|
| collector rebuild/recreate | pass |
| catalog 写入 | pass（1373） |
| 读写顺序 | pass（守护在 gate 后启动；不回源读路径） |
