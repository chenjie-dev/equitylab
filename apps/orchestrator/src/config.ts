/**
 * 编排层运行时配置（环境即真相）。
 * 工具循环上限对齐立项：最多 5 轮、单工具 30s。
 */

export const PORT = Number(process.env.PORT ?? 8001);
export const RESEARCH_URL = process.env.RESEARCH_URL ?? "http://127.0.0.1:8002";
export const MARKET_DATA_URL = process.env.MARKET_DATA_URL ?? "http://127.0.0.1:3002";
export const MAX_TOOL_ROUNDS = 5;
export const TOOL_TIMEOUT_MS = 30_000;
export const DEFAULT_CHAT_MODEL = process.env.DEFAULT_CHAT_MODEL ?? "deepseek-chat";

export function hasModelKey(): boolean {
  return Boolean(process.env.OPENAI_API_KEY || process.env.DEEPSEEK_API_KEY);
}
