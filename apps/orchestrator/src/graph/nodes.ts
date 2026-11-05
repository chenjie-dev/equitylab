/**
 * Graph 节点：route → plan → execute → synthesize。
 *
 * 对齐 `docs/agents/2026-10-27-agent-开发流程与设计清单.md`：
 * 模型只规划；算数在 research。计划只产出注册表里的工具名。
 * A 股六位码必须走 `get_cn_equity_quote`，避免 market-data mock 的演示价。
 * execute 截断到 `MAX_TOOL_ROUNDS`。synthesize 是 MVP stub：有工具失败时不得把结果说成已算出的行情/IC/回测。
 */

import { hasModelKey, MAX_TOOL_ROUNDS } from "../config.js";
import { runToolCall } from "../tools/registry.js";
import type { AgentKind, GraphState, PlannedCall } from "./state.js";
import { appendTrace } from "./state.js";

/** 意图路由节点（LLM 分类后续可替换本节点）。 */
export function routeNode(state: GraphState): Partial<GraphState> {
  const agent = resolveAgent(state.message, state.preferredAgent);
  return appendTrace({ ...state, agent }, `route→${agent}`);
}

function resolveAgent(message: string, preferred: GraphState["preferredAgent"]): AgentKind {
  if (preferred !== "auto") return preferred;
  const m = message.toLowerCase();
  if (m.includes("因子") || m.includes("ic") || m.includes("factor")) return "factor";
  if (m.includes("回测") || m.includes("策略") || m.includes("均线")) return "strategy";
  if (m.includes("股价") || m.includes("行情") || m.includes("多少钱") || m.includes("quote")) {
    return "data";
  }
  return "research";
}

/** Planner：按 Agent 生成工具调用计划。 */
export function planNode(state: GraphState): Partial<GraphState> {
  const planned = planTools(state.agent, state.message);
  return appendTrace({ ...state, planned }, `plan→${planned.map((p) => p.name).join(",") || "∅"}`);
}

function planTools(agent: AgentKind, message: string): PlannedCall[] {
  if (agent === "data") {
    // 六位码是 A 股：读 cn-equity。字母交易对才走 market-data（币安等）。
    const cn = message.match(/\b(\d{6})(?:\.(?:SH|SZ|BJ))?\b/i);
    if (cn) {
      return [{ name: "get_cn_equity_quote", args: { codes: cn[1] } }];
    }
    const spot = message.match(/\b[A-Za-z]{2,20}USDT\b/);
    if (spot) {
      return [{ name: "get_stock_quote", args: { symbol: spot[0].toUpperCase() } }];
    }
    return [{ name: "get_cn_equity_quote", args: { codes: "600519" } }];
  }
  if (agent === "factor") {
    const uni = message.match(/\b\d{6}(?:\.(?:SH|SZ|BJ))?\b/)?.[0] ?? "600519";
    return [
      {
        name: "compute_factor_ic",
        args: { factor: "momentum", windowYears: 3, universe: uni },
      },
    ];
  }
  if (agent === "research") {
    return [{ name: "search_reports", args: { query: message } }];
  }
  if (agent === "strategy") {
    const fast = Number(message.match(/(\d+)\s*[/／]\s*(\d+)/)?.[1] ?? 20);
    const slow = Number(message.match(/(\d+)\s*[/／]\s*(\d+)/)?.[2] ?? 60);
    return [
      {
        name: "run_backtest",
        args: { strategy: "dual_ma", fast, slow, universe: "000300.SH" },
      },
    ];
  }
  return [];
}

/** Executor：顺序执行工具（上限 MAX_TOOL_ROUNDS）。 */
export async function executeNode(state: GraphState): Promise<Partial<GraphState>> {
  const toolResults = [];
  for (const call of state.planned.slice(0, MAX_TOOL_ROUNDS)) {
    toolResults.push(await runToolCall(call.name, call.args));
  }
  return appendTrace({ ...state, toolResults }, `execute→${toolResults.length} tools`);
}

/** Synthesize：MVP stub。只转述工具观察；失败结果显式标出，避免假成功。 */
export function synthesizeNode(state: GraphState): Partial<GraphState> {
  const failed = state.toolResults.filter((r) => !r.ok).length;
  const header = hasModelKey()
    ? `[agent=${state.agent}] 模型 Key 已配置；MVP stub 仍走确定性 synthesize（后续替换为 LLM 节点）。`
    : `[agent=${state.agent}] 未配置模型 Key；以下为确定性工具结果摘要。`;
  const honesty =
    failed > 0
      ? `有 ${failed} 个工具失败：不得把 error 当成行情、IC 或回测结论。`
      : state.toolResults.length === 0
        ? "未调用工具：不得编造价格或指标。"
        : "结论只解释下列工具观察。";
  const answer = [
    header,
    honesty,
    `用户问题：${state.message}`,
    "工具结果：",
    JSON.stringify(state.toolResults, null, 2),
  ].join("\n");
  return appendTrace({ ...state, answer }, "synthesize→done");
}
