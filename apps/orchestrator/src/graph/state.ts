/**
 * LangGraph 风格共享状态（手写轻量实现，便于后续替换为官方 StateGraph）。
 *
 * 设计对齐 langgraph-fundamentals：
 * - 原始数据进 state；提示词在节点内按需组装
 * - messages / toolResults 用「追加」语义
 */

import type { ToolName, ToolResult } from "../tools/registry.js";

export type AgentKind = "research" | "factor" | "strategy" | "data";

export type PlannedCall = { name: ToolName; args: Record<string, unknown> };

export type GraphState = {
  message: string;
  preferredAgent: "auto" | AgentKind;
  agent: AgentKind;
  planned: PlannedCall[];
  toolResults: ToolResult[];
  answer: string;
  /** 节点执行轨迹，便于调试 / 审计 */
  trace: string[];
};

export function createInitialState(
  message: string,
  preferredAgent: GraphState["preferredAgent"] = "auto",
): GraphState {
  return {
    message,
    preferredAgent,
    agent: "research",
    planned: [],
    toolResults: [],
    answer: "",
    trace: [],
  };
}

/** 追加式合并（模拟 reducer）。 */
export function appendTrace(state: GraphState, step: string): GraphState {
  return { ...state, trace: [...state.trace, step] };
}
