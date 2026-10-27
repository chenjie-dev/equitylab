---
name: equitylab-agent-dev
description: >-
  EquityLab Agent / harness 开发流程。Use when adding or changing orchestrator
  tools, agent loops, RAG/tool calling, MCP surfaces, traces/evals, or when the
  user says Agent 开发 / harness / 工具注册 / eval / 轨迹评测. Complements
  equitylab-dev (服务落地) and equitylab-dod (完成门禁).
---

> **中文说明**：按主流开源 harness 实践约束本仓 **Agent 侧**改动——工具契约、轨迹、评测、权限与改进飞轮。数据面/Compose 细节仍走 **equitylab-dev**；收尾走 **equitylab-dod**。

# EquityLab Agent 开发

业界共识（AGENTS.md 仓规、OpenAI Agent Evals / improvement loop、Promptfoo trajectory、DenisSergeevitch harness-evals、GitHub awesome-copilot harness-engineering）：**测的是「模型 + harness」整环**，不是裸模型；**断言轨迹与工具**，不只看散文答案；**仓库是 SSOT**，关键不变量用测试/CI 钉死。

## 何时加载

- 改 `apps/orchestrator` 工具注册、路由、轮次/超时  
- 改 research 上被 Agent 调用的 API（因子/回测/RAG）契约或 `demo`/`mode`  
- 新增 MCP 工具面、权限分级、Trace/eval 样例  
- 用户明确说 Agent 开发 / harness / 工具 / eval  

**不替代**：行情采集 / `market` schema → **equitylab-dev** + 行情边界文档。

## 硬性流程（按序；每步有完成判据）

### 1. Spec 先于工具

写清：用户任务、可用工具、成功/失败、禁止动作、成本与步数预算。  
**完成**：有可勾选验收条（可进 DoD）；无「感觉更智能」类模糊目标。

### 2. 工具进注册表

本仓唯一入口：[`apps/orchestrator/src/tools/registry.ts`](../../../apps/orchestrator/src/tools/registry.ts)。

每条工具必须有：`name` + 人类可读 `description` + Zod schema + `run`。  
**完成**：编排层不绕过注册表直打下游；新能力先扩 registry（或 MCP 再映射进 registry），禁止散落 `fetch`。

### 3. 确定性算数 ⊥ 模型规划

因子 IC / 回测 / 行情数字在 **research 确定性引擎**；模型只规划、选工具、解释。  
响应须带：`mode` / `source`（或 `data_source`）；演示路径标明 `demo`；**禁止**伪随机冒充生产指标。  
**完成**：缺数 → 空/4xx/降级说明，不编造价格或 IC。

### 4. 边界与权限（always / ask / never）

对齐仓规与行情边界：

| 档 | 例 |
|---|---|
| always | 工具超时、`MAX_TOOL_ROUNDS`、TraceId 透传、读路径零上游 |
| ask | 扩 MCP 写面、提高轮次/超时、改公开 API 契约 |
| never | 业务回源公开行情、接真实券商下单、密钥进仓、stub 当生产夏普 |

**完成**：危险能力有硬闸（超时/轮次/不下单），不只靠 prompt「请勿」。

### 5. 轨迹可观测

每次工具调用可关联 `X-Trace-Id` / 编排日志（tool start/ok/fail）。  
**完成**：失败能用 trace 回答「调了谁、参数、错在哪」；不靠猜。

### 6. Eval 门禁（改 harness 必过）

单元在测：**部署中的 scaffold**（指令 + 工具 + 路由 + 停止规则）。  
最少：

1. **轨迹断言**（优先）：是否调用预期工具、禁止调用危险工具、步数/超时是否触发。  
2. **契约断言**：HTTP/工具 JSON 含关键字段（如 `demo`/`source`/`ic`）。  
3. **冒烟脚本**：能复跑（例：`scripts/smoke-factor-ic.sh`；或 compose 内 curl）。

评测维度参考业界五维（正确性 /  groundedness / 安全 / 轨迹 / 成本延迟）——本仓先做可自动化的 1–3，LLM-as-judge 非必须。  
样例形状见 [reference.md](reference.md)。  
**完成**：本改动至少一条可复现命令绿；仅 `health=200` **不算** Agent 能力完成。

### 7. 改进飞轮

失败 trace → 固化成回归 case → 改 harness（工具描述/schema/路由/闸）→ 重跑 eval。  
**完成**：同一失败不能只靠「再试一次 prompt」关掉；能进脚本或测试的要进仓。

## 与流水线关系

```text
equitylab-pipeline（规划…） → 本 skill（Agent 契约/eval） → equitylab-dev（服务实现） → equitylab-dod（收尾）
```

小改可跳过 pipeline 规划，但 **§6 冒烟/eval 不可跳**。

## 反模式（正向替代）

| 不要 | 要 |
|---|---|
| 堆多角色聊天无人审边界 | 注册表工具 + 轮次/超时 + 确定性引擎 |
| 只看最终自然语言对不对 | 断言工具调用与 JSON 契约 |
| 伪 IC/假夏普撑场面 | `demo`/`mode` 诚实或真接冷库 |
| 评测只活在聊天记录里 | case 进 `scripts/` 或 `tests/` |
| AGENTS/skill 写百科 | 短流程 + 链到 docs；不变量用 CI/脚本钉 |

## 收尾句式

对人简报：`已做 / 未做 / 已知风险 / 复验命令`（与 DoD 一致）。
