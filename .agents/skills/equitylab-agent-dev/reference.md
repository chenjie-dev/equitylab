# Agent 开发 — 参考（按需）

完整流程与**市面应考虑问题勾选清单**（人读 SSOT）：

[`docs/agents/2026-10-27-agent-开发流程与设计清单.md`](../../../docs/agents/2026-10-27-agent-开发流程与设计清单.md)

## 业界实践来源（摘要）

| 主题 | 要点 | 公开材料 |
|---|---|---|
| Harness 整环 | 评测指令+工具+权限+停止规则，非裸模型 | [OpenAI Harness Engineering](https://openai.com/index/harness-engineering/) |
| Trace → 数据集 | 先 trace 找失败模式，再固化 eval | [OpenAI Agent Evals](https://developers.openai.com/api/docs/guides/agent-evals) |
| 轨迹优先 | 断言 tool calls / 禁止工具 / 步数 | Promptfoo trajectory；DenisSergeevitch/agents-best-practices |
| 行为套件 | 失败模式 → 灵活断言 → 批量稳定性 | [Google: Anatomy of Harness Engineering](https://developers.googleblog.com/the-anatomy-of-harness-engineering-how-to-evaluate-iterate-and-guard-ai-coding-agents/) |
| 权限与最小工具面 | always / ask；服务端闸 | Anthropic Managed Agents secure deployment |
| MCP 安全 | 描述投毒、最小权限、人审写操作 | [OWASP MCP Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html) |
| 弃权优于瞎猜 | 评分勿只奖 accuracy | OpenAI hallucination / scoring incentives |
| 仓规短地图 | AGENTS.md 作指针，细节进 docs/skill | 本仓 [AGENTS.md](../../../AGENTS.md) |

读本文件不能替代打开原文核对版本；冲突以本仓 `AGENTS.md` + 行情边界为准。

## 本仓落点

| 能力 | 路径 |
|---|---|
| 工具注册 | `apps/orchestrator/src/tools/registry.ts` |
| 工具循环上限 | ≤5 轮、单工具 ≤30s（AGENTS 立项） |
| 因子 IC（冷库） | `apps/research/app/factors/momentum_ic.py`；`POST /factors/ic` |
| 冒烟例 | `scripts/smoke-factor-ic.sh` |
| 可观测 | `docs/platform/2026-10-16-observability.md` |
| 完成门禁 | **equitylab-dod**；数据面见行情边界 SSOT |

## Eval case 最小形状

```yaml
id: factor-ic-cold-path
task: "对 SSE:600519 计算 20 日动量 IC（冷库）"
expect:
  tools_called: ["factor_ic"]
  tools_forbidden: ["broker_order"]
  response_json:
    demo: false
    source: "market"
    ic: { type: number }
  max_tool_rounds: 5
smoke: "scripts/smoke-factor-ic.sh"
```

轨迹与契约优先；LLM-as-judge 不作唯一门禁。

## 权限速查

- **always**：超时、轮次、零上游、Trace、不下真实单  
- **ask**：扩写工具、改公开契约、提高预算  
- **never**：业务回源、密钥入库、demo 当生产  
