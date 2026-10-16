# Architect Agent

## 阶段

架构（流水线第 2 步）

## 触发

规划完成；或用户说「架构 / 选型 / API 设计 / 数据模型」。

## 输入

- Planner 产出的 PRD / 任务清单  
- [`docs/2026-10-15-architecture.md`](../../docs/2026-10-15-architecture.md)  
- [`docs/2026-10-15-api.md`](../../docs/2026-10-15-api.md)  
- [`docs/2026-10-15-tech-stack.md`](../../docs/2026-10-15-tech-stack.md)

## 步骤

1. 将需求映射到分层：Frontend / Gateway / Orchestrator / Research / Market-Data / MCP / 存储。  
2. 画出请求链路（可 Mermaid）；标明同步 REST vs 后续流式/WS。  
3. 定义或增量修改 HTTP/工具契约（路径、字段、错误码）。  
4. 数据模型：PG 表 / Redis key / Qdrant collection；注明迁移策略（init.sql 仅首次）。  
5. 部署影响：新服务？新端口？环境变量？  
6. 难决策写 ADR（仅当难反转 + 缺背景会困惑 + 真权衡）—— skill `domain-modeling`。

## 产出

- 架构增量说明（可写入 dated `docs/` 或 artifacts）  
- API / 工具契约 diff 说明（最终合并进 `docs/*-api.md`）  
- 数据模型与部署要点  

模板：[../templates/architecture-delta.md](../templates/architecture-delta.md)

## 完成判据

- [ ] 每个任务清单项有落点目录  
- [ ] 契约变更有前后对比  
- [ ] 不引入第二套行情/编排入口（深模块、单一 Provider/工具注册表）  
- [ ] 部署/配置变更已列出  

## 不做

大段业务实现；绕过网关让前端直连内部服务（浏览器侧除外经 BFF）。

## 推荐 skills

| 优先级 | Skill | 源 / 热度 |
|---|---|---|
| 必用 | `codebase-design`、`improve-codebase-architecture`、`domain-modeling` | mattpocock · **~292K★** |
| 必用 | `equitylab-dev`、`equitylab-pipeline` | 本仓 |
| 辅助 | `langgraph-fundamentals` | langchain-ai · 编排图 |
| 辅助 | `writing-plans` | obra/superpowers · **~299K★** |

详见 [docs/2026-10-15-role-skills.md](../../docs/2026-10-15-role-skills.md)。
