# EquityLab 技术栈与版本（Agent 平台）

> **SSOT（单一事实来源）**。升级依赖时同步更新本文件与各服务清单（`Cargo.toml` / `package.json` / `requirements`）。  
> 最后更新：2026-10-15（移除 Java，切换多语言 Agent 架构）

选型依据（立项结论）：模型与算法层 **Python**；产品化、Agent 交付与前端 **TypeScript**；网关与行情等高性能边车 **Rust**。不强制单一「最适合 AI」的语言。

## 1. 分层选型

| 层级 | 语言/框架 | 版本基线 | 职责 |
|---|---|---|---|
| 交互层 | TypeScript + Next.js / React | Next **15** / React **19** | 对话、看板 |
| 编排层 | TypeScript + Express（LangGraph 预留） | Node **20+**（镜像 alpine） | Agent 路由、工具调用 |
| 研究层 | Python + FastAPI | Python **3.12** | RAG/因子/回测（确定性计算） |
| 网关 | Rust + Axum | 镜像 `rust:1-bookworm` / Axum **0.8** | 鉴权、限流、反代 |
| 行情 | Rust + Axum | 同上 | Quote/Bars、缓存、Provider |
| 存储 | PostgreSQL / Redis / Qdrant | PG **16** / Redis **7** / Qdrant **1.13** | 结构化数据、缓存、向量 |

前端 UI 规划：Tailwind + shadcn/ui、Zustand、ECharts / Lightweight Charts、Vercel AI SDK（流式）；MVP 为精简对话壳。

## 2. 模型与数据

| 能力 | 默认 | 说明 |
|---|---|---|
| 聊天模型 | DeepSeek / OpenAI（外呼） | 无 Key 时 deterministic 工具链仍可运行 |
| Embedding | text-embedding-3-large（可换 BGE） | RAG 阶段启用 |
| 行情 Provider | `mock`（默认可运行） | 可切 `alphafeed` |

## 3. 明确不做（相对旧 Java 方案）

- Java / Spring Boot / MyBatis 业务单体  
- 本地 vLLM 推理层（统一走外部模型 API）  
- 真实券商下单  

## 4. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-10-15 | 按立项文档改造：去掉 Java，落地 TS/Python/Rust 多服务 MVP 骨架；补齐 API/工程文档 |
| 2026-09-28 | （历史）Java 数据底座阶段；已退役 |
