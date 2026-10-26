# EquityLab Agent Skills

仓库级硬约定：[../../AGENTS.md](../../AGENTS.md)。推荐目录：[../../docs/agents/2026-10-15-agent-skills-catalog.md](../../docs/agents/2026-10-15-agent-skills-catalog.md)。  
锁文件：根目录 [`skills-lock.json`](../../skills-lock.json)（`npx skills` 安装记录）。

## 来源说明

1. **流程类**：源自 `deeplexcloud/.agents/skills`（mattpocock 系等）+ 本仓 **equitylab-dev**。  
2. **栈专用**：经 `npx skills add … -y -a cursor --copy` 安装（LangGraph / RAG / FastAPI / Rust / Redis / PG / Qdrant / shadcn / Docker 等）。

## 未拉取（刻意跳过）

`prisma-*`、`fastify-best-practices`、`vite`、`pnpm`、`linting-neostandard-eslint9` 等与当前栈不符的技能。

## 索引

### 本仓专用

| Skill | 用途 |
|---|---|
| [equitylab-pipeline](./equitylab-pipeline/SKILL.md) | **研发布流水线**：规划→架构→开发→测试→评审→部署→运维；调度 `.agents/team/` 角色 |
| [equitylab-dod](./equitylab-dod/SKILL.md) | **完成判据**：变更分级、冒烟证据、数据面门禁；收尾强制自检 |
| [equitylab-dev](./equitylab-dev/SKILL.md) | 改 gateway / orchestrator / research / market-data / frontend / Compose |

角色卡：[../team/README.md](../team/README.md) · 流水线文档：[../../docs/agents/2026-10-15-agent-pipeline.md](../../docs/agents/2026-10-15-agent-pipeline.md)

### 文档与领域

| Skill | 用途 |
|---|---|
| [writing-for-agents](./writing-for-agents/SKILL.md) | 写 AGENTS.md / skill / 给 agent 的文档 |
| [domain-modeling](./domain-modeling/SKILL.md) | 术语表 CONTEXT.md、ADR |
| [research](./research/SKILL.md) | 一手来源调研并落盘 Markdown |

### 设计与实现

| Skill | 用途 |
|---|---|
| [grilling](./grilling/SKILL.md) / [grill-me](./grill-me/SKILL.md) / [grill-with-docs](./grill-with-docs/SKILL.md) | 拷问式压测方案 |
| [codebase-design](./codebase-design/SKILL.md) | 深模块、seam、adapter |
| [improve-codebase-architecture](./improve-codebase-architecture/SKILL.md) | 架构改进评估 |
| [prototype](./prototype/SKILL.md) | 一次性原型验证逻辑或 UI |
| [implement](./implement/SKILL.md) | 按 spec 实现 |
| [tdd](./tdd/SKILL.md) | 测试驱动 |

### 质量与协作

| Skill | 用途 |
|---|---|
| [diagnosing-bugs](./diagnosing-bugs/SKILL.md) | 硬 bug / 性能诊断闭环 |
| [code-review](./code-review/SKILL.md) | Standards + Spec 双轴审查 |
| [commit](./commit/SKILL.md) | `type: 中文` 提交 |
| [resolving-merge-conflicts](./resolving-merge-conflicts/SKILL.md) | 合并冲突 |

### Agent / RAG / 编排（skills.sh 安装）

| Skill | 来源 | 用途 |
|---|---|---|
| [langgraph-fundamentals](./langgraph-fundamentals/SKILL.md) | langchain-ai/langchain-skills | LangGraph 基础 |
| [langchain-rag](./langchain-rag/SKILL.md) | langchain-ai/langchain-skills | LangChain RAG |
| [mcp-builder](./mcp-builder/SKILL.md) | anthropics/skills | 构建 MCP Server |
| [ai-sdk](./ai-sdk/SKILL.md) | vercel/ai | Vercel AI SDK 流式对话 |

### 研究层 / 网关行情 / 存储

| Skill | 来源 | 用途 |
|---|---|---|
| [fastapi](./fastapi/SKILL.md) | fastapi/fastapi | FastAPI 实践 |
| [rust-async-patterns](./rust-async-patterns/SKILL.md) | wshobson/agents | Rust 异步 |
| [redis-core](./redis-core/SKILL.md) | redis/agent-skills | Redis 核心用法 |
| [supabase-postgres-best-practices](./supabase-postgres-best-practices/SKILL.md) | supabase/agent-skills | Postgres 最佳实践 |
| [qdrant-clients-sdk](./qdrant-clients-sdk/SKILL.md) | qdrant/skills | Qdrant 客户端 SDK |

### 前端 / TypeScript / 容器

| Skill | 来源 | 用途 |
|---|---|---|
| [typescript-magician](./typescript-magician/SKILL.md) | deeplexcloud | TypeScript 技巧 |
| [vercel-react-best-practices](./vercel-react-best-practices/SKILL.md) | vercel-labs（副本） | React / Next 实践 |
| [tailwind-v4-shadcn](./tailwind-v4-shadcn/SKILL.md) | deeplexcloud | Tailwind v4 + shadcn |
| [shadcn](./shadcn/SKILL.md) | shadcn-ui/ui | 官方 shadcn skill |
| [multi-stage-dockerfile](./multi-stage-dockerfile/SKILL.md) | github/awesome-copilot | 多阶段 Dockerfile |
| [docker-patterns](./docker-patterns/SKILL.md) | affaan-m/ecc · ~280K★ | 容器模式 |
| [webapp-testing](./webapp-testing/SKILL.md) | anthropics · ~181K★ | Web / E2E 测试 |
| [prd-development](./prd-development/SKILL.md) / [user-story](./user-story/SKILL.md) | deanpeters · ~7.4K★ | PM 规划 |
| [writing-plans](./writing-plans/SKILL.md) / [brainstorming](./brainstorming/SKILL.md) | obra/superpowers · ~299K★ | 计划 / 头脑风暴 |
| [frontend-design](./frontend-design/SKILL.md) | anthropics | 前端设计 |
| [playwright-cli](./playwright-cli/SKILL.md) | microsoft | Playwright CLI |
| [rag-architect](./rag-architect/SKILL.md) / [devops-engineer](./devops-engineer/SKILL.md) | jeffallan · ~12K★ | RAG / DevOps |
| [differential-review](./differential-review/SKILL.md) / [semgrep](./semgrep/SKILL.md) | trailofbits · ~7.6K★ | 安全审查 |

## 同步 / 更新

```bash
# 更新已装 skills.sh 技能
npx skills update -p -y

# 从 deeplexcloud 覆盖某流程技能
cp -R ~/git/deeplexcloud/.agents/skills/<name> .agents/skills/<name>
```

与本仓 `AGENTS.md` 冲突时，以 **EquityLab `AGENTS.md` 为准**。
