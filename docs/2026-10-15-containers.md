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

卷：`equitylab-pgdata`、`equitylab-qdrant`。

## 关键环境变量

完整列表见仓库根目录 `.env.example`。常用项：

| 变量 | 默认/示例 | 作用 |
|---|---|---|
| `GATEWAY_PORT` / `FRONTEND_PORT` / `MARKET_DATA_PORT` | 3000 / 3001 / 3002 | 宿主机映射 |
| `REDIS_PORT` | 16379 | Redis 宿主机端口 |
| `DATABASE_URL` / `REDIS_URL` | 指向 compose 服务名 | 容器内互联 |
| `MARKET_PROVIDER` | `mock` | `mock` \| `alphafeed` |
| `RATE_LIMIT_PER_MINUTE` | 120 | 网关滑动窗口 |
| `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | 空 | 有 Key 时标记已配置；MVP 仍返回工具摘要 |
| `NEXT_PUBLIC_GATEWAY_URL` | `http://localhost:3000` | 浏览器访问网关 |

服务间 URL 使用 Docker DNS（`http://orchestrator:8001` 等），不要写 `localhost`。

## 常用命令

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
docker compose logs -f gateway orchestrator research market-data

curl http://localhost:3000/health
curl http://localhost:3002/quotes/600519.SH
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

## Schema 初始化

`infra/postgres/init.sql` 在 Postgres **首次**初始化时挂载执行，包含 `klines`、`audit_events`、`chat_sessions`。已有数据卷时改 SQL 不会自动重跑，需手工迁移或重建卷。
