# Agent rules — EquityLab

本文件是仓库级 **agent 行为规范的唯一权威来源**。Cursor、Codex、Claude Code 及其他编码代理均须遵守。  
细则技能见 [`.agents/skills/`](.agents/skills/)；本文件只放跨工具、每次会话都应生效的硬性约定。

写给 agent 看的文档写法见 skill **writing-for-agents**。领域术语见根目录 [`CONTEXT.md`](CONTEXT.md)。

## 项目是什么

EquityLab 是面向量化研究的 **多语言 AI Agent 平台**（非 Java 单体）：

```text
Frontend (Next.js) → Gateway (Rust) → Orchestrator (TS) → Research (Python)
                              ↘ Market-Data (Rust)
存储：PostgreSQL + Redis + Qdrant；模型走外部 API（无本地 vLLM）
```

目录约定：`apps/*` 应用、`services/*` 边车、`docs/*` 人读架构文档、`.agents/skills/` agent 技能、`.agents/team/` 角色卡。

## 研发布流水线（最小 Agent 团队）

功能开发默认按阶段推进（可由 skill **equitylab-pipeline** 编排）：

```text
规划 → 架构 → 开发 → 测试 → 评审 → 部署 → 运维
```

| Agent 角色 | 阶段 | 主要产出 |
|---|---|---|
| PM / Planner | 需求澄清、任务拆解 | PRD、用户故事、验收标准、任务清单 |
| Architect | 架构设计、技术选型 | 架构图、API 规范、数据模型、部署方案 |
| Frontend | 页面与交互 | 组件、页面、路由、接口对接 |
| Backend | 业务逻辑与数据层 | 接口、服务、数据库脚本、权限控制 |
| Data / RAG | 数据、知识库、向量检索 | 数据管道、Embedding、检索策略、评测集 |
| Test | 自动化测试 | 单元 / 集成 / E2E / 回归 |
| Reviewer / Critic | 质量评审 | 代码审查、安全与规范检查、风险提示 |
| DevOps | 部署与运维 | CI/CD、镜像、发布、监控、告警 |

- 流水线说明：[docs/2026-10-15-agent-pipeline.md](docs/2026-10-15-agent-pipeline.md)  
- 角色卡：[`.agents/team/`](.agents/team/README.md)  
- 交接物落盘：`.agents/artifacts/`（模板在 `.agents/templates/`）  
- 小修复可跳过规划/架构，但须冒烟；**门禁未过不得进入下一阶段**。

## docs 命名

`docs/` 下文档（`.md` / `.html` 等）文件名必须带日期前缀：

```text
YYYY-MM-DD-<标题>.md
```

- 日期用文档**创建日**；不要用修改日改写已有前缀  
- 重大改版可**新建**带新创建日的文件，并更新索引中的链接；勿偷偷改旧文件名日期  
- `docs/scripts/` 下的脚本（若有）不要求日期前缀  
- 新建或移动文档后，同步更新仓库内所有引用路径  
- 当前索引：[docs/2026-10-15-文档索引.md](docs/2026-10-15-文档索引.md)

## 必读指针（按需加载）

| 何时 | 打开 |
|---|---|
| 改架构 / Agent / RAG / 行情分层 | [`docs/2026-10-15-architecture.md`](docs/2026-10-15-architecture.md) |
| 改 HTTP 契约或联调路径 | [`docs/2026-10-15-api.md`](docs/2026-10-15-api.md) |
| Compose / 端口 / 环境变量 / 排障 | [`docs/2026-10-15-containers.md`](docs/2026-10-15-containers.md) |
| 日志 / TraceId / Loki Grafana | [`docs/2026-10-16-observability.md`](docs/2026-10-16-observability.md) |
| 版本与「明确不做」 | [`docs/2026-10-15-tech-stack.md`](docs/2026-10-15-tech-stack.md) |
| 文档与注释规范 | [`docs/2026-10-15-engineering.md`](docs/2026-10-15-engineering.md) |
| 多智能体流水线 | [`docs/2026-10-15-agent-pipeline.md`](docs/2026-10-15-agent-pipeline.md) |
| 领域术语（无实现细节） | [`CONTEXT.md`](CONTEXT.md) |

## 硬性约束

1. **不恢复 Java / Spring 业务单体**；计算进 Python，编排进 TypeScript，网关与行情进 Rust。  
2. **不接真实券商下单**；回测与行情仅为研究 / 模拟。  
3. **私有研报**默认本地向量化（Qdrant）；外呼模型只传必要上下文，不把原文泄到不可信渠道。  
4. **因子 / 回测**在研究层确定性引擎执行；模型只做规划与解释。不要把 IC/回测指标假装成已接 alphalens 的真实结果——stub 须标明 `demo` / MVP。  
5. **工具循环**：编排层最多 5 轮、单工具超时 ≤30s（立项约定）。  
6. **报价缓存** TTL≈3s；盘中 WebSocket 推送不进 MCP（后续独立进程）。  
7. **行为变更同步文档**：改路由 / 端口 / 工具名时更新 `docs/YYYY-MM-DD-api.md`（当前为 `2026-10-15-api.md`）与相关注释。

## 本地运行（环境即真相）

```bash
cp .env.example .env   # 若尚无
docker compose up -d --build
curl -s http://localhost:3000/health
```

Redis 宿主机端口默认 **16379**（见 `.env`）；容器内仍为 `redis:6379`。排障见 `docs/2026-10-15-containers.md`。

## 注释与文档

- 公共 API / 模块边界写清职责与不变量（见 `docs/2026-10-15-engineering.md`）。  
- 不复述下一行字面意思；stub 明确标注后续落点。

## 提交（/commit、提交）

用户说 `/commit`、`提交` 或明确要求 commit 时，遵循 skill **commit**：

- 信息格式：`type: 中文描述`（`feat` / `fix` / `perf` / `refactor` / `chore` / `docs` / `style`）  
- **确认后再提交**（用户已说「提交一次」且未改文案时可直接提交）  
- **不默认 push**；**禁止打 Tag**  
- 不提交密钥（`.env` 含真实 Key 时排除）

## 技能索引

完整列表与选用说明：[`.agents/skills/README.md`](.agents/skills/README.md)。

常用触发：

| 意图 | Skill |
|---|---|
| 设计 / 拷问方案 | `grilling` / `grill-me` / `grill-with-docs` |
| 按 spec 实现 | `implement`（常配 `tdd`） |
| 深模块 / seam | `codebase-design` |
| 领域术语 / ADR | `domain-modeling` |
| 难 bug | `diagnosing-bugs` |
| 对照规范审查 | `code-review` |
| 写 skill / AGENTS | `writing-for-agents` |
| 本仓落地改动 | `equitylab-dev` |
| 按流水线推进功能 | `equitylab-pipeline` |
