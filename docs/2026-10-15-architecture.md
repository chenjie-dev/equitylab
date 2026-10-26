# EquityLab 架构说明

> 对应立项文档的分层设计；本文描述**当前仓库已实现的 MVP**与后续扩展点。

## 1. 目标与关键约束

EquityLab 面向量化研究与投资分析：用自然语言完成研报问答、因子挖掘、策略回测与行情查询。

| 约束 | 工程落点 |
|---|---|
| 私有研报不外泄 | 向量化进 Qdrant；外呼模型只传必要上下文（后续加固） |
| 因子/回测依赖 Python | `apps/research` 确定性引擎；模型只做规划与解释 |
| 高频行情 | collector → qdb；Market-Data / Research 只读；网关限流；Redis TTL≈3s 作边路缓存 |
| 成本控制 | 多模型路由（规划）；无 Key 时仍可跑工具链 |

**明确不做**：本地 vLLM；真实券商下单；Java 业务单体。

## 2. 整体架构

```text
Frontend (Next.js/TS)
        │
        ▼
Gateway (Rust / Axum)  ──鉴权·限流·反代（MVP：限流+反代）
        │
        ├──────────────► Orchestrator (TS) ──► Research (Python/FastAPI)
        │                      │                      │
        │                      └──────────────► Market-Data (Rust)
        │
        └──────────────► Market-Data / Research（路径前缀代理）

存储：PostgreSQL（会话/审计） + Redis（报价边路缓存） + Qdrant（研报向量） + qdb（行情库）
模型：外部 API（OpenAI / Claude / DeepSeek / Azure / 火山），无本地推理层
采集：`services/collector` 唯一回源 → qdb；详见 [2026-10-20-qdb-行情库.md](./2026-10-20-qdb-行情库.md)
```

### 典型请求链路

1. 用户在前端提问  
2. Gateway 校验限流并按路径转发  
3. Orchestrator 路由意图 → 规划工具调用  
4. 调用 Research（RAG/因子/回测）或 Market-Data（报价）  
5. 汇总工具结果生成回答（MVP：确定性摘要；后续 LLM）  
6. 审计写入 PostgreSQL（表已建，写入链路后续）

## 3. 分层职责

| 层级 | 目录 | 技术 | 职责 |
|---|---|---|---|
| 交互层 | `apps/frontend` | Next.js 15 + React | 对话壳、后续看板/图表 |
| 编排层 | `apps/orchestrator` | TypeScript + Express | Agent 粗路由、工具注册、超时与轮次控制 |
| 研究层 | `apps/research` | Python 3.12 + FastAPI | RAG / 因子 / 回测（当前 stub） |
| 网关 | `services/gateway` | Rust + Axum | 统一入口、限流、反代 |
| 行情 | `services/market-data` | Rust + Axum | Quote/Bars、币安/RWA 只读 qdb、边路缓存 |
| 采集 | `services/collector` | Python | 公开源写入 qdb（唯一回源） |
| 存储 | Compose | PG / Redis / Qdrant / qdb | 结构化、缓存、向量、行情库 |

## 4. Agent 与 Function Call

设计模式（后续 LangGraph）：`Planner → Executor → Critic → 输出/重试`。

| Agent | 触发意图（MVP 关键词） | 工具 |
|---|---|---|
| ResearchAgent | 默认 / 研报 | `search_reports` |
| FactorAgent | 因子、IC | `compute_factor_ic` |
| StrategyAgent | 回测、策略、均线 | `run_backtest` → `/backtests/run` |
| DataAgent | 股价、行情、多少钱 | `get_stock_quote` |
| SupervisorAgent | — | 后续多 Agent 分发 |

工具循环：**最大 5 轮**；单工具超时 **≤30s**；失败结果回填，由上层决定是否重试。

工具注册三要素：`name`、`description`、Zod/`schema`（见编排层 `apps/orchestrator/src/tools/registry.ts`）。

编排图（LangGraph 风格，可迁移官方 StateGraph）：

```text
START → route → plan → execute → synthesize → END
```

MCP：`apps/mcp-server`（stdio）暴露行情/研报/因子/回测工具，与编排层工具语义对齐。

## 5. RAG（后续完整流水线）

```text
Loader → Splitter(chunk=800, overlap=150) → Embedding
  → Qdrant → Retriever（可混合+RRF）→ Rerank → Prompt → LLM
```

MVP：`POST /rag/search` 返回演示切片，尚未接 Embedding / Qdrant。

混合检索规划：向量 + BM25 + 元数据过滤；RRF：`score = Σ 1/(k+rank+1)`，`k=60`。

## 6. 行情数据层

| 类型 | 协议 | 说明 |
|---|---|---|
| 写入 | collector → qdb HTTP | `POST /v1/quotes` · `/trades` · `/docs`；Compose 内 `QDB_FEED=0` |
| 实时快照 | GET qdb `/v1/snapshots` 或 `/v1/docs` | A 股 / 币安 ticker；Redis TTL≈3s 仍可做边路 |
| 历史 K 线 | GET qdb `/v1/klines` | 符号 `SSE:` / `SZSE:` / `BSE:` / `BINANCE:` / `ONDO:`；读路径可折叠周期 |
| 盘中推送 | WebSocket | 币安公开流仍直连 market-data，不进 qdb / MCP |

Provider Adapter：`MarketDataProvider` trait；`mock` / `binance` / `alphafeed`。`MARKET_PROVIDER=binance` 时统一 `/quotes` `/bars` 也读 qdb。A 股见 Research `/ashare`。总览：[2026-10-20-qdb-行情库.md](./2026-10-20-qdb-行情库.md)。

## 7. 多模型路由（规划）

| 场景 | 推荐 | 理由 |
|---|---|---|
| 研报摘要/问答 | DeepSeek-V3 | 中文长文本、成本低 |
| 因子代码生成 | GPT-4o / Claude Sonnet | 代码稳定 |
| 策略解释 | DeepSeek-V3 | 性价比 |
| Embedding | text-embedding-3-large | 可换本地 BGE |
| 调试 | GPT-4o-mini | 低延迟 |

## 8. MCP（后续）

标准化上下文：Resources（研报/因子元数据）、Tools（报价/IC/回测）、Prompts（分析模板）。传输：stdio / SSE。

## 9. 相关文档

- [API 参考](./2026-10-15-api.md)  
- [容器与端口](./2026-10-15-containers.md)  
- [qdb 行情库](./2026-10-20-qdb-行情库.md)  
- [技术栈版本](./2026-10-15-tech-stack.md)  
- [工程注释约定](./2026-10-15-engineering.md)
