# EquityLab 容器组

Compose 项目名：`equitylab`。一服务一容器，共享网络 `equitylab-net`。

## 服务一览

| 服务 | 容器名 | 宿主机端口 | 说明 |
|---|---|---|---|
| gateway | equitylab-gateway | 3000 | 统一入口 |
| frontend | equitylab-frontend | 3001 | Web UI（容器内 Next 监听 3000） |
| market-data | equitylab-market-data | 3002 | 行情 API |
| orchestrator | equitylab-orchestrator | （内部 8001） | Agent 编排 |
| research | equitylab-research | （内部 8002） | Python 研究层 |
| postgres | equitylab-postgres | 5432 | 数据库 |
| redis | equitylab-redis | **16379→6379** | 缓存（宿主机默认 16379，避免与本机其他 Redis 冲突） |
| qdrant | equitylab-qdrant | 6333 | 向量库 |
| qdb | equitylab-qdb | 9090 | 行情库（构建上下文 `../qdb`，不回源） |
| collector | equitylab-collector | （内部） | 采集公开行情并写入 qdb |
| loki | equitylab-loki | 3100 | 日志存储 |
| alloy | equitylab-alloy | （内部） | 采集容器日志 → Loki（需 docker.sock） |
| grafana | equitylab-grafana | **3003** | 日志查询 UI（匿名 Viewer） |

卷：`equitylab-pgdata`、`equitylab-qdrant`、`equitylab-qdbdata`、`equitylab-loki`、`equitylab-alloy`、`equitylab-grafana`。

qdb 镜像从同级仓库 `../qdb` 构建，只提供读写接口（`QDB_FEED=0`）。`collector` 是唯一回源方：A 股、币安现货、Ondo 代币化美股写入 `POST /v1/quotes`、`POST /v1/trades`、`POST /v1/docs`。研究层与 market-data 只读 `http://qdb:9090`。用法与排障：[2026-10-20-qdb-行情库.md](./2026-10-20-qdb-行情库.md)。升级或改读写前先读同级 `../qdb/docs/manual/index.md`，保持与 qdb 最新手册一致。

可观测性说明：[2026-10-16-observability.md](./2026-10-16-observability.md)。

## 关键环境变量

完整列表见仓库根目录 `.env.example`。常用项：

| 变量 | 默认/示例 | 作用 |
|---|---|---|
| `GATEWAY_PORT` / `FRONTEND_PORT` / `MARKET_DATA_PORT` | 3000 / 3001 / 3002 | 宿主机映射 |
| `REDIS_PORT` | 16379 | Redis 宿主机端口 |
| `DATABASE_URL` / `REDIS_URL` | 指向 compose 服务名 | 容器内互联 |
| `QDB_URL` / `QDB_PORT` | `http://qdb:9090` / 9090 | research、market-data、collector |
| `QDB_FEED` | `0` | 关闭 qdb 内置采集 |
| `QDB_FEED_CODES` / `COLLECTOR_CODES` | 茅台等 | A 股采集列表 |
| `COLLECTOR_INTERVAL_MS` / `QDB_FEED_MS` | `500` | A 股报价热路径间隔；币安实时走 WS→qdb |
| 客户端包 | `packages/qdb-{py,ts,rs}` | Compose 构建 context 为仓库根以 `COPY packages/` |
| `NEXT_PUBLIC_MARKET_WS_URL` | `ws://localhost:3002` | 前端订 qdb（经 `/qdb/ws`） |
| `BINANCE_REST_URL` / `BINANCE_REST_FALLBACK` | `api.binance.com` / `data-api` | **仅** collector；backfill / WS 断流兜底 |
| `BINANCE_WS_URL` / `BINANCE_WS_FALLBACK` | data-stream / stream.binance.com | collector 订流写 qdb |
| `RATE_LIMIT_PER_MINUTE` | 120 | 网关滑动窗口 |
| `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | 空 | 有 Key 时标记已配置；MVP 仍返回工具摘要 |
| `NEXT_PUBLIC_GATEWAY_URL` | `http://localhost:3000` | 浏览器访问网关 |
| `GRAFANA_PORT` / `LOKI_PORT` | 3003 / 3100 | Grafana / Loki 宿主机端口 |
| `GRAFANA_ADMIN_*` | admin / admin | Grafana 管理员（本地演示） |

服务间 URL 使用 Docker DNS（`http://orchestrator:8001` 等），不要写 `localhost`。

## 常用命令

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
docker compose logs -f gateway orchestrator research market-data collector qdb

curl http://localhost:3000/health
curl -s 'http://localhost:9090/v1/snapshots?symbols=SSE:600519' | head -c 200
curl -s 'http://localhost:3000/api/market/binance/ticker/24hr?symbol=BTCUSDT' | head -c 200
curl -X POST http://localhost:3000/api/chat \
  -H 'content-type: application/json' \
  -d '{"message":"茅台现在多少钱？"}'
```

停止并清理（保留卷）：

```bash
docker compose down
```

## 排障

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `Bind … 6379 failed` | 本机其他 Redis 占用 | `.env` 中改 `REDIS_PORT`（默认已用 16379） |
| `network … active endpoints` | 旧容器（如历史 `equitylab-api`）占网 | `docker rm -f <容器>` 后重试 |
| market-data 日志 Redis warn | 启动瞬间 Redis 未就绪或 URL 错 | 检查 `REDIS_URL=redis://redis:6379`；无缓存仍可返回报价 |
| chat 502 | 编排层未起或路径错误 | `docker compose ps` / `logs orchestrator` |
| 行情空 / 只有几根 K 线 | collector 未写或 late-tick | `logs collector`；见 [qdb 排障](./2026-10-20-qdb-行情库.md) |
| collector 解析不了 `qdb` | 容器网络陈旧 | `docker compose up -d --force-recreate collector` |

## Schema 初始化

`infra/postgres/init.sql` 在 Postgres **首次**初始化时挂载执行，包含 `klines`、`audit_events`、`chat_sessions`。已有数据卷时改 SQL 不会自动重跑，需手工迁移或重建卷。
