/**
 * EquityLab 编排层 HTTP 入口。
 *
 * 业务图见 `graph/run.ts`（LangGraph 风格状态机）。
 * @see docs/2026-10-15-architecture.md
 * @see docs/2026-10-15-api.md
 */

import cors from "cors";
import express from "express";
import { z } from "zod";
import { PORT } from "./config.js";
import { runChatGraph } from "./graph/run.js";
import { listTools } from "./tools/registry.js";

const ChatRequestSchema = z.object({
  message: z.string().min(1),
  sessionId: z.string().optional(),
  agent: z
    .enum(["auto", "research", "factor", "strategy", "data"])
    .default("auto"),
});

const app = express();
app.use(cors());
app.use(express.json({ limit: "2mb" }));

app.get("/health", (_req, res) => {
  res.json({ status: "UP", service: "orchestrator", ts: new Date().toISOString() });
});

app.get("/tools", (_req, res) => {
  res.json(listTools());
});

/**
 * 对话主入口。经网关时路径为 POST /api/chat。
 * 响应增加 `trace` 便于对齐 LangGraph 节点调试。
 */
app.post("/api/chat", async (req, res) => {
  const parsed = ChatRequestSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.flatten() });
    return;
  }
  const { message, agent } = parsed.data;
  try {
    const out = await runChatGraph({ message, agent });
    res.json(out);
  } catch (err) {
    res.status(500).json({
      error: err instanceof Error ? err.message : String(err),
    });
  }
});

app.listen(PORT, () => {
  console.log(`equitylab-orchestrator listening on :${PORT}`);
});
