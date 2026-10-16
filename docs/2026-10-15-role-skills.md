# 各角色推荐 Agent Skills（高 star / 高安装量）

> 抓取约 2026-10-15。度量：**GitHub Stars**（源仓信誉）+ **skills.sh installs**（采用热度）。  
> 流水线角色见 [2026-10-15-agent-pipeline.md](./2026-10-15-agent-pipeline.md)；角色卡见 [`.agents/team/`](../.agents/team/README.md)。

图例：✅ 已在本仓 `.agents/skills/` · ⬜ 建议补装

## 总表

| 角色 | 首选 skill | 源仓 Stars（约） | installs（约） | 状态 |
|---|---|---:|---:|---|
| PM / Planner | `deanpeters/…@prd-development` / `@user-story` | 7.4K | 4.6K / 4K | ✅ |
| PM / Planner | `obra/superpowers@writing-plans` / `@brainstorming` | **299K** | 273K / 393K | ✅ |
| PM / Planner | `mattpocock@grill-me` / `grill-with-docs` | **292K** | 百万级 | ✅ |
| Architect | `codebase-design` / `improve-codebase-architecture` / `domain-modeling` | **292K** | 高 | ✅ |
| Frontend | `vercel-react-best-practices` / `frontend-design` / `shadcn` / `ai-sdk` | 32K–181K | 高 | ✅ |
| Backend | `fastapi` / `rust-async-patterns` / `rust-best-practices` / `langgraph` / `mcp-builder` / `redis-core` | 见详表 | — | ✅ |
| Data / RAG | `langchain-rag` / `qdrant-clients-sdk` / `rag-architect` | 1.3K–12K | — | ✅ |
| Test | `tdd` / `diagnosing-bugs` / `playwright-cli` / `webapp-testing` | 高 | — | ✅ |
| Reviewer | `code-review` / `differential-review` / `semgrep` | 7.6K–292K | — | ✅ |
| DevOps | `multi-stage-dockerfile` / `devops-engineer` / `docker-patterns` / PG practices | 高 | — | ✅ |

## 按角色详解

### 1. PM / Planner

| Skill | Stars / installs | 用途 |
|---|---|---|
| [prd-development](https://skills.sh/deanpeters/product-manager-skills/prd-development) | 7.4K★ / 4.6K | 结构化 PRD |
| [user-story](https://skills.sh/deanpeters/product-manager-skills/user-story) | 7.4K★ / 4K | 用户故事 + 验收 |
| [writing-plans](https://skills.sh/obra/superpowers/writing-plans) | **299K★** / 273K | 实现计划 |
| [brainstorming](https://skills.sh/obra/superpowers/brainstorming) | **299K★** / 393K | 方案发散收敛 |
| grill-me / grill-with-docs | **292K★** / 百万级 | 拷问需求（已有） |

仓：[deanpeters/product-manager-skills](https://github.com/deanpeters/product-manager-skills) · [obra/superpowers](https://github.com/obra/superpowers)

### 2. Architect

| Skill | Stars / installs | 用途 |
|---|---|---|
| codebase-design / improve-codebase-architecture / domain-modeling | **292K★** | 深模块、ADR、术语（已有） |
| [langgraph-fundamentals](https://skills.sh/langchain-ai/langchain-skills/langgraph-fundamentals) | 1.3K★ / 17K | 编排图设计（已有） |
| equitylab-dev | 本仓 | EquityLab 分层落点 |

### 3. Frontend

| Skill | Stars / installs | 用途 |
|---|---|---|
| vercel-react-best-practices | **32K★** / 802K | React/Next（已有） |
| [frontend-design](https://skills.sh/anthropics/skills/frontend-design) | **181K★** / 989K | 高质量 UI |
| shadcn / ai-sdk | 高 | 组件与流式（已有） |

### 4. Backend

| Skill | Stars / installs | 用途 |
|---|---|---|
| fastapi / rust-async / langgraph / mcp-builder / redis-core | 见上 | 已有 |
| [rust-best-practices](https://skills.sh/apollographql/skills/rust-best-practices) | 117★ / 20K | Rust 工程实践 |
| supabase-postgres-best-practices | 2.8K★ / 445K | PG（已有） |

### 5. Data / RAG

| Skill | Stars / installs | 用途 |
|---|---|---|
| langchain-rag / qdrant-clients-sdk | 官方向 | 已有 |
| [rag-architect](https://skills.sh/jeffallan/claude-skills/rag-architect) | **12K★** / 4.5K | RAG 架构方法 |

### 6. Test

| Skill | Stars / installs | 用途 |
|---|---|---|
| tdd / diagnosing-bugs | **292K★** | 已有 |
| [webapp-testing](https://skills.sh/anthropics/skills/webapp-testing) | **181K★** / 177K | Web 测试 |
| [playwright-cli](https://skills.sh/microsoft/playwright-cli/playwright-cli) | 官方 / 184K | E2E |

### 7. Reviewer / Critic

| Skill | Stars / installs | 用途 |
|---|---|---|
| code-review | **292K★** / 736K | 双轴审查（已有） |
| [differential-review](https://skills.sh/trailofbits/skills/differential-review) | **7.6K★** / 7.8K | 安全向差分审查 |
| [semgrep](https://skills.sh/trailofbits/skills/semgrep) | **7.6K★** / 9K | SAST 指引 |

仓：[trailofbits/skills](https://github.com/trailofbits/skills)

### 8. DevOps

| Skill | Stars / installs | 用途 |
|---|---|---|
| multi-stage-dockerfile | **40K★** | 已有 |
| [docker-patterns](https://skills.sh/affaan-m/ecc/docker-patterns) | **280K★** / 13K | 容器模式 |
| [devops-engineer](https://skills.sh/jeffallan/claude-skills/devops-engineer) | **12K★** / 11K | DevOps 工程 |

## 建议补装命令

```bash
npx skills add deanpeters/product-manager-skills@prd-development -y -a cursor --copy
npx skills add deanpeters/product-manager-skills@user-story -y -a cursor --copy
npx skills add obra/superpowers@writing-plans -y -a cursor --copy
npx skills add obra/superpowers@brainstorming -y -a cursor --copy
npx skills add anthropics/skills@frontend-design -y -a cursor --copy
npx skills add anthropics/skills@webapp-testing -y -a cursor --copy
npx skills add microsoft/playwright-cli@playwright-cli -y -a cursor --copy
npx skills add apollographql/skills@rust-best-practices -y -a cursor --copy
npx skills add jeffallan/claude-skills@rag-architect -y -a cursor --copy
npx skills add jeffallan/claude-skills@devops-engineer -y -a cursor --copy
npx skills add trailofbits/skills@differential-review -y -a cursor --copy
npx skills add trailofbits/skills@semgrep -y -a cursor --copy
npx skills add affaan-m/ecc@docker-patterns -y -a cursor --copy
```

## 刻意不推荐（热但偏题）

- 飞书 / Hyperframes / 纯视频类（安装量虚高，与 EquityLab 无关）  
- Prisma / Fastify / Convex 全家桶（非本栈）  
- Azure 合规全家桶（非当前云目标）  
