/**
 * 工具注册表：name + description + Zod schema + run。
 * 编排层与外部系统交互的唯一入口（equitylab-dev / Function Call 约定）。
 * 下游 HTTP 透传 X-Trace-Id。
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
    schema: z.object({ symbol: z.string().min(1) }),
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
      codes: z.string().min(1).describe("逗号分隔代码，如 600519,000001"),
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
    schema: z.object({ query: z.string().min(1) }),
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
    description: "计算因子 IC / ICIR（Python 研究层确定性引擎）",
    schema: z.object({
      factor: z.string().min(1),
      windowYears: z.number().int().min(1).max(10).default(3),
    }),
    async run(args: { factor: string; windowYears: number }): Promise<unknown> {
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
      strategy: z.string().default("dual_ma"),
      fast: z.number().int().positive().default(20),
      slow: z.number().int().positive().default(60),
      universe: z.string().default("000300.SH"),
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
