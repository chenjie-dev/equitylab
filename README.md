# EquityLab — A 股投研 Agent 工作台 / 多服务行情与研究平台

本地优先的多语言系统：用自然语言做研报检索、因子/回测（研究层确定性计算）与行情查询。  
**研究与模拟用途；不接真实券商下单。** 已移除 Java 业务单体。

## 架构

```text
Frontend (Next.js) → Gateway (Rust) → Orchestrator (TS) → Research (Python)
                         ↘ Market-Data (Rust，只读 qdb)
采集族（仅此可回源）:
  collector          → qdb + 部分 market
  history-ingest     → market.bar_daily（新浪冷日线）
  adata-ingest       → market.*（冷域 P0–P3）
  akshare-ingest     → market.*（并行冷灌，不改 schema）
存储: PostgreSQL(market) + Redis + Qdrant + qdb
```

| 层级 | 目录 | 技术 |
|---|---|---|
| 交互 | `apps/frontend` | Next.js + React |
| 编排 | `apps/orchestrator` | TypeScript；工具注册表 + 轮次/超时 |
| 研究 | `apps/research` | Python 3.12 + FastAPI；RAG / 因子 / 回测 / `cn-equity` |
| MCP | `apps/mcp-server` | TypeScript + MCP SDK（stdio） |
| 网关 | `services/gateway` | Rust + Axum |
| 行情读 | `services/market-data` | Rust；非 A 股读 qdb；`/qdb/ws` 代理 |
| 采集族 | `services/{collector,history-ingest,adata-ingest,akshare-ingest}` | 授权回源写热/冷库 |
| 客户端包 | `packages/qdb-*`、`packages/market-py` | 业务禁止裸打 `QDB_URL` / 自拼 PG 行情写 |
| 存储 | Compose | PostgreSQL / Redis / Qdrant / qdb |

**数据面不变量：**

- 热库 qdb = 盘中；冷库 `market` = 已闭合历史与维表；产品读面名是 **cn-equity**，不是供应商名。  
- 读路径**零上游**：research / market-data / frontend 不得直打公开行情 HTTP；缺数 → 空/503，等采集补。  
- 新数据源 = 登记 `data_source` + 灌**既有表**；禁止为 SDK 分叉 schema。

细则：[行情模块边界](docs/market/2026-10-26-行情模块边界.md)、[CONTEXT.md](CONTEXT.md)、[AGENTS.md](AGENTS.md)。

## 快速启动

依赖：Docker Compose；构建 qdb 需同级仓库 `../qdb`（见 [containers](docs/platform/2026-10-15-containers.md)）。

```bash
cp .env.example .env
# 按需填写 OPENAI_API_KEY / DEEPSEEK_API_KEY 等

docker compose up -d --build
```

| 入口 | 地址 |
|---|---|
| Gateway（推荐统一入口） | http://localhost:3000/health |
| Frontend（亦可直连） | http://localhost:3001 |
| Market Data | http://localhost:3002/health |
| Grafana / Prometheus | :3003 / :9091 |
| PostgreSQL / Redis / Qdrant / qdb | :5432 / :16379 / :6333 / :9090 |

### 冒烟（非仅 health）

```bash
curl -sf http://localhost:3000/health
curl -sf "http://localhost:3000/api/cn-equity/codes?limit=3" | head -c 400
curl -sf -X POST http://localhost:3000/api/chat \
  -H 'content-type: application/json' \
  -d '{"message":"茅台现在多少钱？"}'
```

编排层工具（见 `apps/orchestrator/src/tools/registry.ts`）：`get_quote`、`get_cn_equity_quote`、`rag_search`、`compute_factor_ic`、`run_backtest`（后两者若仍为演示路径，响应须标明 stub/demo）。

## 硬性约束

1. 私有研报默认本地向量化（Qdrant）；外呼模型只带必要上下文。  
2. 因子 / 回测在研究层确定性引擎执行；模型只做规划与解释。  
3. 不接真实券商下单；无本地 vLLM（走外部模型 API）。  
4. 行情：授权采集族可回源；业务读路径零上游；报价缓存约 3s；盘中 WS 不进 MCP。  
5. 编排：工具循环上限与单工具超时（立项约定，见架构文档）。

## 文档

| 文档 | 内容 |
|---|---|
| [文档索引](docs/2026-10-26-文档索引.md) | `docs/` 入口 |
| [架构与 Agent](docs/platform/2026-10-15-architecture.md) | 链路、工具、RAG、模型路由 |
| [API](docs/platform/2026-10-15-api.md) | HTTP 契约 |
| [容器与端口](docs/platform/2026-10-15-containers.md) | Compose、env、排障 |
| [行情模块边界](docs/market/2026-10-26-行情模块边界.md) | 热冷 / 采集族 / 命名（SSOT） |
| [akshare-ingest](docs/market/2026-10-27-akshare-ingest.md) | 并行冷采集边车 |
| [可观测性](docs/platform/2026-10-16-observability.md) | Trace / Loki / Grafana |
| [AGENTS.md](AGENTS.md) | 编码 Agent 硬性约定 |
| [CONTEXT.md](CONTEXT.md) | 领域术语 |

## 现状与后续

**已有：**多服务 Compose、网关/前端/编排/研究、A 股 cn-equity 读面与行情台、采集族（盘中 + 冷日线 + adata/akshare 冷灌）、qdb 客户端包、`market` 冷域表、基础可观测。

**后续：**因子 IC / 回测生产化与可复现产物；编排工具回归；MCP 与编排对齐。以代码与 `.agents/artifacts/*-dod.md` 为准。
