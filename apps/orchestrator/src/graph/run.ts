/**
 * 编译并运行线性图：START → route → plan → execute → synthesize → END。
 * 官方 @langchain/langgraph 接入时，保持节点函数签名即可迁移。
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
