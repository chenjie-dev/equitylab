# EquityLab 多智能体研发布流水线

> 本仓库用 **最小 Agent 团队** 按固定阶段推进功能：  
> **规划 → 架构 → 开发 → 测试 → 评审 → 部署 → 运维**  
> 角色卡与交接门禁见 [`.agents/team/`](../.agents/team/README.md)；编排入口 skill：`equitylab-pipeline`。

## 1. 流水线总览

```text
PM/Planner ──► Architect ──► Frontend + Backend + Data/RAG
                                   │
                                   ▼
                              Test Agent
                                   │
                                   ▼
                           Reviewer/Critic
                                   │
                                   ▼
                             DevOps Agent
                                   │
                                   ▼
                              运维观察 ←── 回流缺陷到 Planner
```

| 阶段 | 负责角色 | 主要产出 | 进入下一阶段的门禁 |
|---|---|---|---|
| 规划 | PM / Planner | PRD、用户故事、验收标准、任务清单 | 验收标准可测；范围与「明确不做」对齐 |
| 架构 | Architect | 架构增量说明、API/数据变更、部署影响 | 契约路径明确；分层不越界 |
| 开发 | Frontend / Backend / Data-RAG | 代码、迁移脚本、工具/RAG 变更 | 对应冒烟路径可跑 |
| 测试 | Test | 单测/集成/E2E/回归用例与报告 | 关键路径绿；失败有复现命令 |
| 评审 | Reviewer / Critic | 双轴审查（Standards + Spec）、风险清单 | 阻断项清零或经人确认豁免 |
| 部署 | DevOps | 镜像、Compose/CI 变更、发布说明 | `docker compose` 健康检查通过 |
| 运维 | DevOps（兼） | 监控/告警/排障笔记 | 已知故障有 runbook 指针 |

并行规则：**Frontend / Backend / Data-RAG** 可在架构门禁通过后并行，但共享契约（`docs/*-api.md`）由 Architect 锁定后再改。

## 2. 最小 Agent 团队

| Agent 角色 | 流程阶段 | 主要产出 | 角色卡 |
|---|---|---|---|
| PM / Planner Agent | 需求澄清、任务拆解 | PRD、用户故事、验收标准、任务清单 | [01-pm-planner](../.agents/team/01-pm-planner.md) |
| Architect Agent | 架构设计、技术选型 | 架构图、API 规范、数据模型、部署方案 | [02-architect](../.agents/team/02-architect.md) |
| Frontend Agent | 页面与交互实现 | 组件、页面、路由、接口对接 | [03-frontend](../.agents/team/03-frontend.md) |
| Backend Agent | 业务逻辑与数据层 | 接口、服务、数据库脚本、权限控制 | [04-backend](../.agents/team/04-backend.md) |
| Data / RAG Agent | 数据、知识库、向量检索 | 数据管道、Embedding、检索策略、评测集 | [05-data-rag](../.agents/team/05-data-rag.md) |
| Test Agent | 自动化测试 | 单元测试、集成测试、E2E、回归用例 | [06-test](../.agents/team/06-test.md) |
| Reviewer / Critic Agent | 质量评审 | 代码审查、安全扫描、规范检查、风险提示 | [07-reviewer](../.agents/team/07-reviewer.md) |
| DevOps Agent | 部署与运维 | CI/CD、容器镜像、发布、监控、告警 | [08-devops](../.agents/team/08-devops.md) |

单会话缺省：由当前编码代理按 `equitylab-pipeline` **分阶段扮演**；大任务可拆多会话/子代理，但交接物必须落盘。

## 3. 仓库落点（EquityLab 映射）

| 产出类型 | 默认落点 |
|---|---|
| PRD / 故事 / 任务清单 | `.agents/artifacts/YYYY-MM-DD-<topic>-prd.md` 等 |
| 架构 / API / 数据模型 | `docs/YYYY-MM-DD-*.md`（创建日新文件或更新当前 SSOT 并改引用） |
| 前端 | `apps/frontend` |
| 网关 / 编排 / 行情 / MCP | `services/gateway`、`apps/orchestrator`、`services/market-data`、`apps/mcp-server` |
| 研究 / RAG / 因子 | `apps/research` |
| Schema | `infra/postgres/init.sql`（已有卷需另写迁移说明） |
| Compose / 健康检查 | `docker-compose.yml`、各服务 Dockerfile |
| 评审记录 | `.agents/artifacts/YYYY-MM-DD-<topic>-review.md` |

模板：[`.agents/templates/`](../.agents/templates/)。

## 4. 硬约束（全角色共享）

见根目录 [`AGENTS.md`](../AGENTS.md) 与 [`CONTEXT.md`](../CONTEXT.md)。摘要：

- 分层：TS 编排 / Python 计算 / Rust 网关与行情；禁止恢复 Java 单体  
- 无实盘下单；stub 必须标明 `demo`  
- 私有研报本地向量化；工具 ≤5 轮、超时 ≤30s；报价缓存 TTL≈3s  
- **生产级迭代**：变更分级（hotfix/feature/epic）、DoD、数据面不变量、评审阻断项——见 AGENTS「生产级迭代」与 [`2026-10-26-agent-dod-与数据面门禁.md`](./2026-10-26-agent-dod-与数据面门禁.md)  
- 模板：[`.agents/templates/dod.md`](../.agents/templates/dod.md)；skill：`equitylab-dod`

## 5. 如何启动一轮流水线

对人：

```text
按 equitylab-pipeline 做：<一句话目标>
从规划开始 / 从架构开始 / 只做开发+测试 …
```

对代理：打开 skill **equitylab-pipeline**，按当前阶段加载对应 `.agents/team/0N-*.md`，完成门禁后再进入下一阶段。

小修复（单文件 typo、文案）可跳过规划/架构，但仍须 **冒烟证据**；feature/epic 结束前强制 **equitylab-dod**。

整轮简报须含：`已做 / 未做 / 已知风险 / 复验命令`。

## 6. 各角色高星 Skills

每个角色对应的 GitHub 高 star / skills.sh 高安装量技能见：

**[docs/agents/2026-10-15-role-skills.md](./2026-10-15-role-skills.md)**

角色卡内「推荐 skills」表与该文档同步；优先用已安装到 `.agents/skills/` 的副本。
