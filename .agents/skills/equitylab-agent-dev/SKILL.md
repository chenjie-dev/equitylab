---
name: equitylab-agent-dev
description: >-
  EquityLab Agent / harness 开发流程。Use when adding or changing orchestrator
  tools, agent loops, RAG/tool calling, MCP surfaces, traces/evals, or when the
  user says Agent 开发 / harness / 工具注册 / eval / 轨迹评测. Complements
  equitylab-dev (服务落地) and equitylab-dod (完成门禁).
---

> **中文说明**：约束本仓 **Agent 侧**改动——工具契约、轨迹、评测、权限与改进飞轮。设计前勾选清单见人读 SSOT；数据面/Compose 走 **equitylab-dev**；收尾走 **equitylab-dod**。

# EquityLab Agent 开发

**测的是「模型 + harness」整环**，不是裸模型；**断言轨迹与工具**，不只看散文；**仓库是 SSOT**，不变量用脚本/CI 钉死。

人读流程 + 市面应考虑问题（完整勾选）：[`docs/agents/2026-10-27-agent-开发流程与设计清单.md`](../../../docs/agents/2026-10-27-agent-开发流程与设计清单.md)。  
Eval 样例与来源链：[reference.md](reference.md)。

## 何时加载

- 改 `apps/orchestrator` 工具注册、路由、轮次/超时  
- 改 research 上被 Agent 调用的 API（因子/回测/RAG）契约或 `demo`/`mode`  
- 新增 MCP 工具面、权限分级、Trace/eval 样例  
- 用户说 Agent 开发 / harness / 工具 / eval  

**不替代**：行情采集 / `market` schema → **equitylab-dev** + 行情边界。

## 硬性流程（按序）

### 0. 设计前勾选（completion：相关项已过一遍）

打开 [设计清单 §2](../../../docs/agents/2026-10-27-agent-开发流程与设计清单.md)：工具职责、轨迹/grounded、权限闸、停止预算、回归固化、本仓数据面。  
feature/epic 把未适用项划掉并在 DoD/简报写一句；hotfix 至少过安全闸与假成功两项。

### 1. Spec 先于工具

写清：用户任务、可用工具、成功/失败、禁止动作、轮次/超时/成本预算。  
**完成**：可勾选验收条；无「感觉更智能」类目标。加 planner/多 Agent/重试前先对照**单环基线**是否值得。

### 2. 工具进注册表

入口：[`apps/orchestrator/src/tools/registry.ts`](../../../apps/orchestrator/src/tools/registry.ts)。

每条：`name` + 人类可读 `description` + Zod schema + `run`。单一职责、少重叠；错误结构化返回。  
**完成**：编排层不绕过注册表；新能力先扩 registry（MCP 映射进 registry），禁止散落 `fetch`。

### 3. 确定性算数 ⊥ 模型规划

因子 IC / 回测 / 行情在 **research 确定性引擎**；模型只规划、选工具、解释。  
响应带 `mode` / `source`（或 `data_source`）；演示标 `demo`；无证据则弃权/降级，**不编造**价格或 IC。  
**完成**：契约字段可被 smoke/单测断言。

### 4. 边界与权限（always / ask / never）

| 档 | 例 |
|---|---|
| always | 工具超时、`MAX_TOOL_ROUNDS`、TraceId、读路径零上游 |
| ask | 扩 MCP 写面、提高轮次/超时、改公开 API 契约 |
| never | 业务回源公开行情、真实券商下单、密钥进仓、stub 当生产指标 |

闸在**执行层**；用户输入与工具返回当不可信数据。  
**完成**：超时/轮次/不下单可测，不只靠 prompt「请勿」。

### 5. 轨迹可观测

每次工具调用可关联 `X-Trace-Id` / 编排日志（tool start/ok/fail）。  
**完成**：失败能回答「调了谁、参数、观察、停在哪」。

### 6. Eval 门禁（改 harness 必过）

单元在测：**部署中的 scaffold**。最少：

1. **轨迹**：预期工具 / 禁止工具 / 步数或超时触发  
2. **契约**：JSON 关键字段（`demo`/`source`/`ic` 等）  
3. **冒烟**：可复跑脚本或 compose 内 curl  

复杂路径锁不变量与最终状态，勿无谓锁死唯一工具顺序。LLM-as-judge 仅补充。  
**完成**：至少一条可复现命令绿；仅 `health=200` **不算** Agent 能力完成。

### 7. 改进飞轮

失败 trace → 固化回归 case → 改 harness（描述/schema/路由/闸）→ 重跑 eval。  
Agent **不得**改自己的 grader/冒烟断言。  
**完成**：同一失败不能只靠「再试一次 prompt」。

## 与流水线

```text
pipeline → 设计清单勾选 → 本 skill → equitylab-dev → equitylab-dod
```

小改可跳过 pipeline 规划；**§0 相关勾选 + §6 eval 不可跳**。

## 反模式 → 正向

| 不要 | 要 |
|---|---|
| 堆多角色无人审边界 | 注册表 + 轮次/超时 + 确定性引擎 |
| 只评最终散文 | 断言工具调用与 JSON 契约 |
| 伪指标撑场面 | `demo`/`mode` 诚实或真接冷库 |
| 评测只活在聊天里 | case 进 `scripts/` / `tests/` |
| 高分但不可部署 | 质量与成本/延迟/安全一起量 |
| 靠 prompt 挡危险 | 执行层 always/ask/never |

## 收尾

简报：`已做 / 未做 / 已知风险 / 复验命令`（与 DoD 一致）。
