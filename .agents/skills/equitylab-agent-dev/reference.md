# Agent 开发 — 参考（按需）

## 业界实践来源（摘要，非产品背书）

| 主题 | 要点 | 公开材料 |
|---|---|---|
| Harness = 整环 | 评测部署中的指令+工具+路由，不是裸模型 | OpenAI Cookbook：Agent Evals；[Harness engineering](https://github.com/github/awesome-copilot/blob/main/agents/harness-engineering.agent.md) |
| 轨迹优先 | 断言 tool calls / 禁止工具 / 步数，不只最终答案 | [Promptfoo agent-trajectory](https://www.promptfoo.dev/docs/guides/evaluate-rag/#agent-trajectory)；DenisSergeevitch/harness-evals |
| 改进飞轮 | 失败 → 固化 case → 改 harness → 重跑 | OpenAI Agent improvement loop；社区 agent-eval / agent-harness 讨论 |
| 仓规 SSOT | AGENTS.md / CLAUDE.md 放硬约定；细节进 skill | 本仓 [AGENTS.md](../../../AGENTS.md)；writing-for-agents |
| 工具 schema | 描述给模型；参数 Zod/JSON Schema；单一注册表 | OpenAI/Anthropic tool-calling；本仓 `TOOL_REGISTRY` |

读本文件不能替代打开上述原文核对版本；本仓落地以 registry + smoke + DoD 为准。

## 本仓落点

| 能力 | 路径 |
|---|---|
| 工具注册 | `apps/orchestrator/src/tools/registry.ts` |
| 工具循环上限 | 编排层最多 5 轮、单工具 ≤30s（AGENTS 立项约定） |
| 因子 IC（冷库） | `apps/research/app/factors/momentum_ic.py`；`POST /factors/ic` |
| 冒烟例 | `scripts/smoke-factor-ic.sh` |
| 可观测 | `docs/platform/2026-10-16-observability.md`（TraceId） |
| 完成门禁 | skill **equitylab-dod**；数据面另见行情边界 SSOT |

## Eval case 最小形状

用 YAML/JSON/脚本均可；字段语义对齐即可：

```yaml
id: factor-ic-cold-path
task: "对 SSE:600519 计算 20 日动量 IC（冷库）"
expect:
  tools_called: ["factor_ic"]          # 或编排侧等价工具名
  tools_forbidden: ["broker_order"]  # 若存在下单类面
  response_json:
    demo: false
    source: "market"                   # 或契约约定字段
    ic: { type: number }               # 类型/存在性，勿锁死浮点
  max_tool_rounds: 5
smoke: "scripts/smoke-factor-ic.sh"
```

轨迹断言优先于「答案像不像分析师」；LLM-as-judge 仅作补充，不作唯一门禁。

## 权限分级速查

- **always**：超时、轮次、读路径零上游、Trace 透传、不下真实单  
- **ask**：扩写工具、改公开契约、提高预算  
- **never**：业务回源公开行情、密钥入库、demo 指标当生产  

细则与行情不变量见 [AGENTS.md](../../../AGENTS.md) 与 `docs/market/2026-10-26-行情模块边界.md`。
