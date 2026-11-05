/**
 * 工具注册表：编排层打下游的唯一入口。
 *
 * 契约见 `docs/agents/2026-10-27-agent-开发流程与设计清单.md`：
 * 每条工具必须有 name、人类可读 description、Zod schema、run。
 * 错误结构化返回 `{ ok:false, data.error }`，禁止把失败当成行情或 IC。
 * 下游只打 research / market-data，并透传 `X-Trace-Id`；禁止公开行情回源与真实下单。
 * 单次 `run` 受 `TOOL_TIMEOUT_MS` 限制。
 */

import { z } from "zod";
import { MARKET_DATA_URL, RESEARCH_URL, TOOL_TIMEOUT_MS } from "../config.js";
import { log, TRACE_HEADER, traceHeaders } from "../tracing.js";

export type ToolResult = { name: string; ok: boolean; data: unknown };

function jsonHeaders(): Record<string, string> {
  return { "content-type": "application/json", ...traceHeaders() };
}

export const TOOL_REGISTRY = {
  get_stock_quote: {
    description:
      "按证券代码查询最新行情快照（币安/RWA 等非 A 股；A 股请用 get_cn_equity_quote）",
    schema: z.object({
      symbol: z
        .string()
        .min(1)
        .describe("非 A 股符号，如 BTCUSDT；A 股六位码走 get_cn_equity_quote"),
    }),
    async run(args: { symbol: string }): Promise<unknown> {
      const res = await fetch(
        `${MARKET_DATA_URL}/quotes/${encodeURIComponent(args.symbol)}`,
        { headers: traceHeaders() },
      );
      if (!res.ok) {
        throw new Error(`market-data ${res.status}: 检查符号或行情服务是否可用`);
      }
      return res.json();
    },
  },
  get_cn_equity_quote: {
    description:
      "查询中国 A 股报价（research /cn-equity；支持 600519 或 SSE:000001）",
    schema: z.object({
      codes: z
        .string()
        .min(1)
        .describe("A 股代码，逗号分隔，如 600519,000001；读 research 冷库/历史报价"),
    }),
    async run(args: { codes: string }): Promise<unknown> {
      const q = new URLSearchParams({ codes: args.codes });
      const res = await fetch(
        `${RESEARCH_URL}/cn-equity/quotes?${q}`,
        { headers: traceHeaders() },
      );
      if (!res.ok) {
        throw new Error(`cn-equity quotes ${res.status}`);
      }
      return res.json();
    },
  },

  search_reports: {
    description: "在私有研报库中检索相关切片（RAG）",
    schema: z.object({
      query: z.string().min(1).describe("检索问句；只返回库内切片，无命中不得编造研报"),
    }),
    async run(args: { query: string }): Promise<unknown> {
      const res = await fetch(`${RESEARCH_URL}/rag/search`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(args),
      });
      if (!res.ok) {
        throw new Error(`research ${res.status}: RAG 检索失败，可缩小查询或稍后重试`);
      }
      return res.json();
    },
  },
  compute_factor_ic: {
    description:
      "计算 A 股单标的动量时序 IC/ICIR（研究层冷库日线；非伪随机、非截面）",
    schema: z.object({
      factor: z.string().min(1).default("momentum").describe("目前仅 momentum"),
      windowYears: z.number().int().min(1).max(10).default(3).describe("回看年数"),
      universe: z.string().min(1).default("600519").describe("单标的六位码"),
      lookback: z.number().int().min(1).max(120).optional().describe("动量回看交易日"),
      horizon: z.number().int().min(1).max(60).optional().describe("前瞻收益交易日"),
    }),
    async run(args: {
      factor: string;
      windowYears: number;
      universe: string;
      lookback?: number;
      horizon?: number;
    }): Promise<unknown> {
      const res = await fetch(`${RESEARCH_URL}/factors/ic`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(args),
      });
      if (!res.ok) {
        throw new Error(`research ${res.status}: 因子计算失败`);
      }
      return res.json();
    },
  },
  run_backtest: {
    description:
      "运行双均线等策略回测（研究层；A 股日线优先 market 冷库，其它走 market-data）",
    schema: z.object({
      strategy: z.string().default("dual_ma").describe("目前仅 dual_ma；研究模拟，不下真实单"),
      fast: z.number().int().positive().default(20).describe("快均线"),
      slow: z.number().int().positive().default(60).describe("慢均线，须大于 fast"),
      universe: z.string().default("000300.SH").describe("标的，A 股优先冷库日线"),
    }),
    async run(args: {
      strategy: string;
      fast: number;
      slow: number;
      universe: string;
    }): Promise<unknown> {
      const res = await fetch(`${RESEARCH_URL}/backtests/run`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(args),
      });
      if (!res.ok) {
        throw new Error(`research ${res.status}: 回测失败`);
      }
      return res.json();
    },
  },
} as const;

export type ToolName = keyof typeof TOOL_REGISTRY;

export function listTools(): Array<{ name: string; description: string }> {
  return Object.entries(TOOL_REGISTRY).map(([name, t]) => ({
    name,
    description: t.description,
  }));
}

/** 带超时的单工具执行；异常转为 ok:false 回填（供模型/上层决定是否重试）。 */
export async function runToolCall(
  name: ToolName,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  const tool = TOOL_REGISTRY[name];
  try {
    const parsed = tool.schema.parse(args);
    log("info", "tool start", { tool: name });
    const data = await Promise.race([
      tool.run(parsed as never),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error(`tool timeout after ${TOOL_TIMEOUT_MS}ms`)), TOOL_TIMEOUT_MS),
      ),
    ]);
    log("info", "tool ok", { tool: name });
    return { name, ok: true, data };
  } catch (err) {
    log("warn", "tool failed", {
      tool: name,
      error: err instanceof Error ? err.message : String(err),
      header: TRACE_HEADER,
    });
    return {
      name,
      ok: false,
      data: { error: err instanceof Error ? err.message : String(err) },
    };
  }
}
