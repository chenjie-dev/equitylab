/**
 * 统一日志 + X-Trace-Id 上下文（AsyncLocalStorage）。
 * 字段与网关/研究层对齐：traceId / service / level / msg / ts。
 */

import { AsyncLocalStorage } from "node:async_hooks";
import { randomUUID } from "node:crypto";
import type { NextFunction, Request, Response } from "express";

export const TRACE_HEADER = "x-trace-id";
export const SERVICE = "orchestrator";

type Store = { traceId: string };

const als = new AsyncLocalStorage<Store>();

export function currentTraceId(): string {
  return als.getStore()?.traceId ?? "";
}

export function traceHeaders(): Record<string, string> {
  const id = currentTraceId();
  return id ? { [TRACE_HEADER]: id } : {};
}

export function log(
  level: "info" | "warn" | "error",
  msg: string,
  extra: Record<string, unknown> = {},
): void {
  const line = {
    ts: new Date().toISOString(),
    level,
    service: SERVICE,
    traceId: currentTraceId() || undefined,
    msg,
    ...extra,
  };
  const text = JSON.stringify(line);
  if (level === "error") {
    console.error(text);
  } else if (level === "warn") {
    console.warn(text);
  } else {
    console.log(text);
  }
}

/** Express：解析/生成 X-Trace-Id，写入响应头，打 access log。 */
export function traceMiddleware(req: Request, res: Response, next: NextFunction): void {
  const incoming = String(req.header(TRACE_HEADER) ?? "").trim();
  const traceId = incoming || randomUUID();
  const started = Date.now();

  als.run({ traceId }, () => {
    res.setHeader(TRACE_HEADER, traceId);
    res.on("finish", () => {
      log("info", "request", {
        method: req.method,
        path: req.path,
        status: res.statusCode,
        latencyMs: Date.now() - started,
      });
    });
    next();
  });
}
