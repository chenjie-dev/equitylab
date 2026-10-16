/**
 * BFF：浏览器 → `/api/ashare/*` → Gateway `/api/research/ashare/*`。
 */

import { NextRequest, NextResponse } from "next/server";
import { logJson, resolveTraceId, TRACE_HEADER } from "@/lib/trace";

const GATEWAY =
  process.env.GATEWAY_URL ??
  process.env.NEXT_PUBLIC_GATEWAY_URL ??
  "http://localhost:3000";

async function proxy(req: NextRequest, path: string[]) {
  const traceId = resolveTraceId(req);
  const started = Date.now();
  const suffix = path.map(encodeURIComponent).join("/");
  const url = new URL(req.url);
  const target = `${GATEWAY}/api/research/ashare/${suffix}${url.search}`;

  try {
    const upstream = await fetch(target, {
      method: "GET",
      headers: { [TRACE_HEADER]: traceId },
      cache: "no-store",
    });
    const text = await upstream.text();
    const outTrace = upstream.headers.get(TRACE_HEADER) ?? traceId;
    logJson("info", "request", {
      traceId: outTrace,
      path: `/api/ashare/${suffix}`,
      status: upstream.status,
      latencyMs: Date.now() - started,
    });
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        "content-type":
          upstream.headers.get("content-type") ?? "application/json",
        [TRACE_HEADER]: outTrace,
      },
    });
  } catch (err) {
    logJson("error", "ashare proxy failed", {
      traceId,
      error: err instanceof Error ? err.message : String(err),
    });
    return NextResponse.json(
      { error: err instanceof Error ? err.message : String(err) },
      { status: 502, headers: { [TRACE_HEADER]: traceId } },
    );
  }
}

export async function GET(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  const { path } = await ctx.params;
  return proxy(req, path);
}
