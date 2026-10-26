/**
 * Prometheus 指标：HTTP 请求计数 / 延迟（路径粗分组）。
 */
import type { NextFunction, Request, Response } from "express";
import client from "prom-client";

client.collectDefaultMetrics({
  labels: { service: "orchestrator" },
});

const httpRequests = new client.Counter({
  name: "http_requests_total",
  help: "Total HTTP requests",
  labelNames: ["method", "path_group", "status", "service"],
});

const httpDuration = new client.Histogram({
  name: "http_request_duration_seconds",
  help: "HTTP request duration seconds",
  labelNames: ["method", "path_group", "service"],
  buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10],
});

function pathGroup(path: string): string {
  const p = path.split("?")[0] || "/";
  if (p === "/health" || p === "/metrics" || p === "/tools") return p;
  if (p.startsWith("/api/chat")) return "/api/chat";
  if (p.startsWith("/v1/")) return "/v1";
  const parts = p.split("/").filter(Boolean);
  if (parts.length === 0) return "/";
  if (parts.length === 1) return `/${parts[0]}`;
  return `/${parts[0]}/${parts[1]}`;
}

export function metricsMiddleware(req: Request, res: Response, next: NextFunction): void {
  if (req.path === "/metrics") {
    next();
    return;
  }
  const start = process.hrtime.bigint();
  const group = pathGroup(req.path);
  res.on("finish", () => {
    const elapsed = Number(process.hrtime.bigint() - start) / 1e9;
    const labels = {
      method: req.method,
      path_group: group,
      service: "orchestrator",
    };
    httpRequests.inc({ ...labels, status: String(res.statusCode) });
    httpDuration.observe(labels, elapsed);
  });
  next();
}

export async function metricsHandler(_req: Request, res: Response): Promise<void> {
  res.set("Content-Type", client.register.contentType);
  res.end(await client.register.metrics());
}
