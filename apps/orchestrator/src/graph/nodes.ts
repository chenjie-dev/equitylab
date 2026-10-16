/**
 * Graph 节点：route → plan → execute → synthesize。
 * 每个节点接收完整 state，返回 partial update。
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
    const symbol = message.match(/\b\d{6}(?:\.(?:SH|SZ))?\b/)?.[0] ?? "600519.SH";
    return [{ name: "get_stock_quote", args: { symbol } }];
  }
  if (agent === "factor") {
    return [{ name: "compute_factor_ic", args: { factor: "momentum", windowYears: 3 } }];
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

/** Synthesize：MVP 返回确定性摘要；有模型 Key 时仍标明后续接 LLM 节点。 */
export function synthesizeNode(state: GraphState): Partial<GraphState> {
  const header = hasModelKey()
    ? `[agent=${state.agent}] 模型 Key 已配置；MVP 仍走确定性 synthesize 节点（后续替换为 LLM 节点）。`
    : `[agent=${state.agent}] 未配置模型 Key；以下为确定性工具结果摘要。`;
  const answer = [
    header,
    `用户问题：${state.message}`,
    "工具结果：",
    JSON.stringify(state.toolResults, null, 2),
  ].join("\n");
  return appendTrace({ ...state, answer }, "synthesize→done");
}
