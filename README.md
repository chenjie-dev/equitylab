# EquityLab — AI 驱动的量化研究与投资分析平台

通过自然语言完成研报分析、因子挖掘、策略回测与行情查询。  
**已移除 Java 单体**；按立项文档采用分层多语言架构。

## 架构（MVP）

```text
前端 (Next.js/TS) → Rust 网关 → TS 编排层 → Python 研究层 → 外部模型 API
                         ↘ Rust 行情服务（只读 qdb）
采集族：collector（盘中→qdb）+ history-ingest（冷日线→market）
存储：PostgreSQL（含 market）+ Redis + Qdrant + qdb
```

| 层级 | 目录 | 技术 |
|---|---|---|
| 交互层 | `apps/frontend` | Next.js 15 + React |
| 编排层 | `apps/orchestrator` | TypeScript + Express（LangGraph 风格状态机） |
| 研究层 | `apps/research` | Python 3.12 + FastAPI + Qdrant 探测 |
| MCP | `apps/mcp-server` | TypeScript + MCP SDK（stdio） |
| 网关 | `services/gateway` | Rust + Axum |
| 行情 | `services/market-data` | Rust + Axum（币安 / RWA 读 qdb） |
| 采集 | `services/collector` | Python（盘中回源 → qdb + 部分 market） |
| 冷历史 | `services/history-ingest` | Python（日线缺口 → market） |
| 共享包 | `packages/qdb-*`、`packages/market-py` | qdb / `equitylab_market` 客户端 |
| 存储 | Compose 服务 | PostgreSQL / Redis / Qdrant / qdb |

## 快速启动

```bash
cp .env.example .env
# 按需填写 OPENAI_API_KEY / DEEPSEEK_API_KEY 等

docker compose up -d --build
```

| 服务 | 地址 |
|---|---|
| Gateway（统一入口） | http://localhost:3000/health |
| Frontend | http://localhost:3001 |
| Market Data | http://localhost:3002/health（也可经网关 `/api/market/*`） |
| Orchestrator | 内部 `8001` |
| Research | 内部 `8002` |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:16379`（容器内仍为 6379） |
| Qdrant | http://localhost:6333 |
| qdb | http://localhost:9090（`GET /v1/snapshots`） |

冒烟：

```bash
curl -s http://localhost:3000/health
curl -s -X POST http://localhost:3000/api/chat \
  -H 'content-type: application/json' \
  -d '{"message":"茅台现在多少钱？"}'
```

## 文档

| 文档 | 内容 |
|---|---|
| [文档索引](docs/2026-10-26-文档索引.md) | `docs/` 入口（文件名均带日期前缀） |
| [技术栈与版本](docs/platform/2026-10-15-tech-stack.md) | 依赖基线与明确不做项 |
| [架构与 Agent](docs/platform/2026-10-15-architecture.md) | 链路、工具、RAG、模型路由 |
| [API 参考](docs/platform/2026-10-15-api.md) | HTTP 契约与示例 |
| [容器组与端口](docs/platform/2026-10-15-containers.md) | Compose、环境变量、排障 |
| [qdb 行情库](docs/market/2026-10-20-qdb-行情库.md) | 本仓落点；最新契约见同级 `../qdb/docs/manual/` |
| [工程约定](docs/platform/2026-10-15-engineering.md) | **文档与代码注释规范** |
| [立项改造说明](docs/platform/2026-10-15-migration.md) | 去 Java 记录 |
| [Agent Skills 目录](docs/agents/2026-10-15-agent-skills-catalog.md) | 栈相关高热 skills 推荐 |
| [多智能体流水线](docs/agents/2026-10-15-agent-pipeline.md) | 规划→架构→开发→测试→评审→部署→运维 |
| [AGENTS.md](AGENTS.md) | 编码 Agent 硬性约定 |
| [CONTEXT.md](CONTEXT.md) | 领域术语 |
| [.agents/skills](.agents/skills/README.md) | 开发用 Agent Skills |
| [.agents/team](.agents/team/README.md) | 最小 Agent 团队角色卡 |

## 关键约束

1. 私有研报本地向量化（Qdrant），不外泄原文到不可信渠道。  
2. 因子/回测在 Python 确定性引擎执行，模型只做规划与解释。  
3. 行情经 collector → qdb；业务层只读；Redis 边路缓存 + 网关限流；盘中 WS 不进 MCP。  
4. 多模型路由按任务复杂度控成本（见 `docs/platform/2026-10-15-architecture.md`）。

## MVP 已落地 / 后续

**已落地：**多服务骨架、健康检查、网关反向代理与限流、行情 Provider trait + Mock/AlphaFeed 骨架、研究层 FastAPI 占位、编排层意图路由与工具调用、前端对话壳、基础 schema 与文档。

**可观测：**Prometheus `:9091` + Grafana `:3003`（Platform / Market 看板）；日志 Loki。见 `docs/platform/2026-10-16-observability.md`。

**后续：**LangGraph 状态机、完整 RAG、MCP Server、真实行情 Provider 与熔断、Token 预算与计费、Langfuse / Alertmanager。
