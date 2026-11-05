/**
 * 单环基线：START → route → plan → execute → synthesize → END。
 *
 * 加 planner / 多 Agent / 重试前先对照本环（见 Agent 开发清单 §1）。
 * 节点签名保持稳定，便于以后换成官方 StateGraph。
 */

import { createInitialState, type GraphState } from "./state.js";
import { executeNode, planNode, routeNode, synthesizeNode } from "./nodes.js";

export type ChatGraphInput = {
  message: string;
  agent?: GraphState["preferredAgent"];
};

export type ChatGraphOutput = {
  agent: GraphState["agent"];
  answer: string;
  toolCalls: GraphState["planned"];
  toolResults: GraphState["toolResults"];
  trace: string[];
};

export async function runChatGraph(input: ChatGraphInput): Promise<ChatGraphOutput> {
  let state = createInitialState(input.message, input.agent ?? "auto");

  state = { ...state, ...routeNode(state) };
  state = { ...state, ...planNode(state) };
  state = { ...state, ...(await executeNode(state)) };
  state = { ...state, ...synthesizeNode(state) };

  return {
    agent: state.agent,
    answer: state.answer,
    toolCalls: state.planned,
    toolResults: state.toolResults,
    trace: state.trace,
  };
}
