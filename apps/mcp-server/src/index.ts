#!/usr/bin/env node
/**
 * EquityLab MCP Server（stdio）
 *
 * 对齐 mcp-builder：工具命名清晰、错误可行动、结果聚焦。
 * Resources / Prompts 后续扩展；盘中 WebSocket 推送不进本服务。
 *
 * 环境变量：
 * - MARKET_DATA_URL（默认 http://127.0.0.1:3002）
 * - RESEARCH_URL（默认 http://127.0.0.1:8002）
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const MARKET_DATA_URL = process.env.MARKET_DATA_URL ?? "http://127.0.0.1:3002";
const RESEARCH_URL = process.env.RESEARCH_URL ?? "http://127.0.0.1:8002";

async function fetchJson(url: string, init?: RequestInit): Promise<unknown> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(
      `上游 ${url} 返回 ${res.status}。请确认服务已启动，并检查符号/参数是否合法。`,
    );
  }
  return res.json();
}

const server = new McpServer({
  name: "equitylab-mcp",
  version: "0.1.0",
});

server.tool(
  "get_stock_quote",
  "查询股票最新行情快照（经 EquityLab market-data）",
  { symbol: z.string().describe("证券代码，如 600519.SH") },
  async ({ symbol }) => {
    const data = await fetchJson(
      `${MARKET_DATA_URL}/quotes/${encodeURIComponent(symbol)}`,
    );
    return {
      content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
    };
  },
);

server.tool(
  "get_daily_bars",
  "查询历史日 K（经 EquityLab market-data）",
  {
    symbol: z.string(),
    count: z.number().int().positive().max(120).default(60),
  },
  async ({ symbol, count }) => {
    const data = await fetchJson(
      `${MARKET_DATA_URL}/bars/${encodeURIComponent(symbol)}?period=1d&count=${count}`,
    );
    return {
      content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
    };
  },
);

server.tool(
  "search_reports",
  "检索私有研报切片（Research RAG；MVP 可能返回 demo hits）",
  { query: z.string().min(1) },
  async ({ query }) => {
    const data = await fetchJson(`${RESEARCH_URL}/rag/search`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query }),
    });
    return {
      content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
    };
  },
);

server.tool(
  "query_factor_ic",
  "查询因子 IC/ICIR（Research；demo stub 时带 demo=true）",
  {
    factor: z.string().default("momentum"),
    windowYears: z.number().int().min(1).max(10).default(3),
  },
  async ({ factor, windowYears }) => {
    const data = await fetchJson(`${RESEARCH_URL}/factors/ic`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ factor, windowYears }),
    });
    return {
      content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
    };
  },
);

server.tool(
  "run_backtest",
  "运行策略回测（Research；非实盘）",
  {
    strategy: z.string().default("dual_ma"),
    fast: z.number().int().positive().default(20),
    slow: z.number().int().positive().default(60),
    universe: z.string().default("000300.SH"),
  },
  async (args) => {
    const data = await fetchJson(`${RESEARCH_URL}/backtests/run`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(args),
    });
    return {
      content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
    };
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
