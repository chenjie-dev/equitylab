---
name: equitylab-pipeline
description: >-
  EquityLab multi-agent delivery pipeline (plan → architecture → develop → test →
  review → deploy → operate). Use when starting a feature, saying 流水线/规划/架构/评审/部署,
  coordinating PM Planner Architect Frontend Backend Data-RAG Test Reviewer DevOps,
  or when the user wants work run as the minimal agent team.
---

> **中文说明**：按「规划→架构→开发→测试→评审→部署→运维」驱动 EquityLab 开发；按阶段加载 `.agents/team/` 角色卡，门禁通过再进入下一阶段。收尾强制 DoD（`equitylab-dod`）。

# EquityLab Pipeline

## 权威文档

- 流水线 SSOT：[`docs/2026-10-15-agent-pipeline.md`](../../../docs/2026-10-15-agent-pipeline.md)
- DoD / 数据面：[`docs/2026-10-26-agent-dod-与数据面门禁.md`](../../../docs/2026-10-26-agent-dod-与数据面门禁.md)
- 角色卡目录：[`../../team/README.md`](../../team/README.md)
- 硬约束：[`AGENTS.md`](../../../AGENTS.md)

## 过程（每轮功能）

1. **定级别与阶段**  
   - 级别：hotfix | feature | epic（见 AGENTS「变更分级」）。  
   - 用户指定起点则听从。  
   - 否则：新需求 → 规划；契约已清且任务明确 → 开发；仅修 bug → 测试回路 + 开发。  
   - hotfix 可跳过规划/架构；**不可跳过冒烟**。用户未说「跳过流水线」时，禁止编码完直接报完成。

2. **加载角色卡**（一次只主扮演一个角色；并行开发可声明 FE/BE/Data 分轨）  
   | 阶段 | 读取 |
   |---|---|
   | 规划 | `team/01-pm-planner.md` |
   | 架构 | `team/02-architect.md` |
   | 开发-前端 | `team/03-frontend.md` |
   | 开发-后端 | `team/04-backend.md` |
   | 开发-数据/RAG | `team/05-data-rag.md` |
   | 测试 | `team/06-test.md` |
   | 评审 | `team/07-reviewer.md` |
   | 部署/运维 | `team/08-devops.md` |

3. **落盘交接物** 到 `.agents/artifacts/`（用 `.agents/templates/`）。未落盘不得声称阶段完成。

4. **门禁自检** 对照角色卡「完成判据」全部勾选后再进入下一阶段。

5. **阶段结束时简报**（固定格式）：

```text
## Pipeline status
- 级别：hotfix | feature | epic
- 阶段：<名>
- 角色：<名>
- 产出：<路径列表>
- 门禁：pass | fail（失败原因）
- 已做 / 未做 / 已知风险 / 复验命令：…
- 下一步：<下一角色/阶段>
```

6. **整轮收尾（feature/epic 强制）**  
   - 打开 skill **equitylab-dod**，填写 [`.agents/templates/dod.md`](../../templates/dod.md) → artifacts。  
   - DoD fail → 回到开发/测试，不得 Deploy。

## 路由捷径

| 用户说法 | 进入 |
|---|---|
| 规划 / PRD / 拆任务 | Planner |
| 架构 / API / 数据模型 | Architect |
| 前端 / 页面 | Frontend |
| 后端 / 网关 / 编排 / 行情 | Backend |
| RAG / 向量 / 研报入库 | Data-RAG |
| 测试 / 冒烟 / 回归 | Test |
| 审查 / review | Reviewer |
| 部署 / CI / 镜像 / 监控 | DevOps |
| DoD / 完成判据 / 可否上线 | `equitylab-dod` |
| 按流水线做完 | 从 Planner 顺序推进到 DevOps，最后 DoD |

## 与其他 skill 的关系

- 实现细节遵守 `equitylab-dev`。  
- 收尾遵守 `equitylab-dod`。  
- 评审用 `code-review` 双轴；阻断项见 AGENTS。  
- 难 bug 用 `diagnosing-bugs`。  
- 需求拷问用 `grilling`。  
- 不要跳过门禁直接「全部做完」后才补文档。
