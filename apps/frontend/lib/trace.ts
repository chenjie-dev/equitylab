/**
 * 前端 Trace 工具：沿用入站 `X-Trace-Id` 或生成 UUID，并打 JSON 日志。
 */

import { randomUUID } from "node:crypto";
import type { NextRequest } from "next/server";

export const TRACE_HEADER = "x-trace-id";
export const SERVICE = "frontend";

export function resolveTraceId(req: NextRequest): string {
  const incoming = req.headers.get(TRACE_HEADER)?.trim();
  return incoming || randomUUID();
}

export function logJson(
  level: "info" | "warn" | "error",
  msg: string,
  extra: Record<string, unknown> = {},
): void {
  const line = JSON.stringify({
    ts: new Date().toISOString(),
    level,
    service: SERVICE,
    msg,
    ...extra,
  });
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.log(line);
}
