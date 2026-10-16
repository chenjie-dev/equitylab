# EquityLab 技术栈相关 Agent Skills 目录

> 来源：[skills.sh](https://skills.sh/) 安装量 + GitHub `stargazers_count`（抓取日约 2026-10-15）。  
> 度量说明：skills 生态常用 **安装量**；仓库 **Stars** 衡量源信誉。二者不完全等价。

本仓已从 deeplexcloud 落地一批通用流程技能（见 [`.agents/skills/README.md`](../.agents/skills/README.md)）。下文按 **EquityLab 栈** 推荐可再安装的高热技能。

## 栈映射

| EquityLab 层 | 技术 | 优先看的官方/高星技能源 |
|---|---|---|
| 前端 | Next.js 15 / React 19 / shadcn | `vercel-labs/agent-skills`、`shadcn-ui/ui`、`anthropics/skills` |
| 编排 | TypeScript / 工具调用 /（规划）LangGraph、Mastra、AI SDK | `langchain-ai/langchain-skills`、`mastra-ai/skills`、`vercel/ai`、`anthropics/skills@mcp-builder` |
| 研究 | Python / FastAPI / RAG | `fastapi/fastapi`、`langchain-ai/langchain-skills@langchain-rag`、`wshobson/agents@fastapi-templates` |
| 网关 / 行情 | Rust / Axum / Redis 缓存 | `apollographql/skills@rust-best-practices`、`wshobson/agents@rust-async-patterns`、`redis/agent-skills`、`actionbook/rust-skills` |
| 存储 | PostgreSQL / Qdrant | `supabase/agent-skills@supabase-postgres-best-practices`、`qdrant/skills`、`wshobson/agents@postgresql-table-design` |
| 工程 | Docker / 多服务 | `github/awesome-copilot@multi-stage-dockerfile`、`affaan-m/ecc@docker-patterns` |

## 强烈推荐（贴合且热度高）

### 前端 / Next / React

| Skill | 安装量（约） | 仓库 Stars（约） | 安装 |
|---|---:|---:|---|
| `vercel-labs/agent-skills@vercel-react-best-practices` | 802K | 32K（repo） | 本仓已有副本 |
| `vercel-labs/agent-skills@web-design-guidelines` | 738K | 同上 | `npx skills add vercel-labs/agent-skills@web-design-guidelines` |
| `vercel-labs/agent-skills@vercel-composition-patterns` | 395K | 同上 | `npx skills add vercel-labs/agent-skills@vercel-composition-patterns` |
| `shadcn-ui/ui@shadcn` | 378K | 126K | `npx skills add shadcn-ui/ui@shadcn` |
| `anthropics/skills@frontend-design` | 989K | 181K | `npx skills add anthropics/skills@frontend-design` |
| `vercel/next.js@next-dev-loop` | 20K | （next.js 主仓） | `npx skills add vercel/next.js@next-dev-loop` |

### Agent / RAG / 编排（立项核心）

| Skill | 安装量（约） | 仓库 Stars（约） | 安装 |
|---|---:|---:|---|
| `langchain-ai/langchain-skills@langgraph-fundamentals` | 17K | 1.3K | `npx skills add langchain-ai/langchain-skills@langgraph-fundamentals` |
| `langchain-ai/langchain-skills@langgraph-persistence` | 17K | 同上 | `npx skills add langchain-ai/langchain-skills@langgraph-persistence` |
| `langchain-ai/langchain-skills@langchain-rag` | 17K | 同上 | `npx skills add langchain-ai/langchain-skills@langchain-rag` |
| `langchain-ai/langchain-skills@deep-agents-orchestration` | 16K | 同上 | `npx skills add langchain-ai/langchain-skills@deep-agents-orchestration` |
| `vercel/ai@ai-sdk` | 66K | 27K | `npx skills add vercel/ai@ai-sdk` |
| `mastra-ai/skills@mastra` | 73K | 96 | `npx skills add mastra-ai/skills@mastra`（立项备选编排；repo 星少，官方产品向） |
| `anthropics/skills@mcp-builder` | 126K | 181K | `npx skills add anthropics/skills@mcp-builder` |

### Python / FastAPI 研究层

| Skill | 安装量（约） | 说明 | 安装 |
|---|---:|---|---|
| `wshobson/agents@fastapi-templates` | 25K | 高星 agents 合集（repo ~41K★） | `npx skills add wshobson/agents@fastapi-templates` |
| `fastapi/fastapi@fastapi` | 12K | 官方框架侧技能 | `npx skills add fastapi/fastapi@fastapi` |
| `mindrally/skills@fastapi-python` | 14K | 社区 FastAPI | `npx skills add mindrally/skills@fastapi-python` |

### Rust / Axum / Redis（网关与行情）

| Skill | 安装量（约） | 仓库 Stars（约） | 安装 |
|---|---:|---:|---|
| `apollographql/skills@rust-best-practices` | 20K | 117 | `npx skills add apollographql/skills@rust-best-practices` |
| `wshobson/agents@rust-async-patterns` | 20K | 41K | `npx skills add wshobson/agents@rust-async-patterns` |
| `actionbook/rust-skills`（多 skill） | 数 K | 1.5K | `npx skills add actionbook/rust-skills` |
| `redis/agent-skills@redis-core` | 3.7K | 167 | `npx skills add redis/agent-skills@redis-core` |
| `upstash/skills@upstash-ratelimit-js` | 19K | 30 | 限流思路可参考；网关为 Rust 实现，勿照搬 JS SDK |

> Axum 专用 skill 安装量普遍 &lt;1K，优先用 **Rust async / best-practices** 再结合本仓 `equitylab-dev`。

### PostgreSQL / Qdrant / Docker

| Skill | 安装量（约） | 仓库 Stars（约） | 安装 |
|---|---:|---:|---|
| `supabase/agent-skills@supabase-postgres-best-practices` | 445K | 2.8K | `npx skills add supabase/agent-skills@supabase-postgres-best-practices` |
| `wshobson/agents@postgresql-table-design` | 27K | 41K | `npx skills add wshobson/agents@postgresql-table-design` |
| `qdrant/skills@qdrant-clients-sdk` | 1.7K | （官方 skills 仓） | `npx skills add qdrant/skills@qdrant-clients-sdk` |
| `qdrant/skills@qdrant-search-quality` | 1.7K | 同上 | `npx skills add qdrant/skills@qdrant-search-quality` |
| `github/awesome-copilot@multi-stage-dockerfile` | 29K | 40K | `npx skills add github/awesome-copilot@multi-stage-dockerfile` |
| `affaan-m/ecc@docker-patterns` | 13K | 280K | `npx skills add affaan-m/ecc@docker-patterns` |

### TypeScript 编排层增强

| Skill | 安装量（约） | 说明 |
|---|---:|---|
| `wshobson/agents@typescript-advanced-types` | 87K | 复杂 Zod / 工具类型 |
| `mattpocock/skills@setup-ts-deep-modules` | 336K | 深模块 TS 结构；本仓流程技能同源 |
| `pproenca/dot-skills@zod` | 6.8K | 工具 schema 与 Zod |

## 已在本仓 / 不必重复装

源自 mattpocock / deeplexcloud 的流程类（grill、tdd、code-review、domain-modeling、writing-for-agents 等）及 `vercel-react-best-practices`、`typescript-magician`、`tailwind-v4-shadcn` 已在 `.agents/skills/`。

## 慎选 / 低相关

- **Prisma / Fastify / Vite / Convex 全家桶**：与当前栈不符，除非明确改 ORM/框架。  
- **纯视频 / 飞书 / Azure 运维合集**：安装量虚高，与 EquityLab MVP 无关。  
- **Axum 小众 skill（&lt;1K installs）**：可作参考，不作为默认权威。

## 建议安装包（最小集）— 已安装（2026-10-15）

下列技能已通过 `npx skills add … -y -a cursor --copy` 落到 `.agents/skills/`，并由根目录 `skills-lock.json` 锁定：

| Skill | 源 |
|---|---|
| langgraph-fundamentals / langchain-rag | langchain-ai/langchain-skills |
| mcp-builder | anthropics/skills |
| ai-sdk | vercel/ai |
| fastapi | fastapi/fastapi |
| rust-async-patterns | wshobson/agents |
| redis-core | redis/agent-skills |
| supabase-postgres-best-practices | supabase/agent-skills |
| qdrant-clients-sdk | qdrant/skills |
| shadcn | shadcn-ui/ui |
| multi-stage-dockerfile | github/awesome-copilot |

更新：`npx skills update -p -y`。索引见 [`.agents/skills/README.md`](../.agents/skills/README.md)。

## 浏览入口

- 总榜：https://skills.sh/  
- 按源：https://skills.sh/vercel-labs/agent-skills 、https://skills.sh/langchain-ai/langchain-skills 、https://skills.sh/anthropics/skills
