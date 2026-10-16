/**
 * BFF：浏览器 → Next `/api/chat` → Gateway `/api/chat`。
 * 透传 / 生成 X-Trace-Id。
 */

import { NextRequest, NextResponse } from "next/server";
import { logJson, resolveTraceId, TRACE_HEADER } from "@/lib/trace";

const GATEWAY =
  process.env.GATEWAY_URL ??
  process.env.NEXT_PUBLIC_GATEWAY_URL ??
  "http://localhost:3000";

export async function POST(req: NextRequest) {
  const traceId = resolveTraceId(req);
  const started = Date.now();
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json(
      { error: "invalid json" },
      { status: 400, headers: { [TRACE_HEADER]: traceId } },
    );
  }

  try {
    const upstream = await fetch(`${GATEWAY}/api/chat`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        [TRACE_HEADER]: traceId,
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const text = await upstream.text();
    const outTrace = upstream.headers.get(TRACE_HEADER) ?? traceId;
    logJson("info", "request", {
      traceId: outTrace,
      path: "/api/chat",
      status: upstream.status,
      latencyMs: Date.now() - started,
    });
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
        [TRACE_HEADER]: outTrace,
      },
    });
  } catch (err) {
    logJson("error", "gateway unreachable", {
      traceId,
      path: "/api/chat",
      error: err instanceof Error ? err.message : String(err),
    });
    return NextResponse.json(
      {
        error: err instanceof Error ? err.message : String(err),
        hint: `无法连接网关 ${GATEWAY}`,
      },
      { status: 502, headers: { [TRACE_HEADER]: traceId } },
    );
  }
}
