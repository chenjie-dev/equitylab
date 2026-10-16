/**
 * BFF：浏览器 → Next `/api/chat` → Gateway `/api/chat`。
 * 避免在客户端硬编码跨域；与 AI SDK 后续 useChat transport 对齐同一路径。
 */

import { NextRequest, NextResponse } from "next/server";

const GATEWAY =
  process.env.GATEWAY_URL ??
  process.env.NEXT_PUBLIC_GATEWAY_URL ??
  "http://localhost:3000";

export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${GATEWAY}/api/chat`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    });
    const text = await upstream.text();
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: err instanceof Error ? err.message : String(err),
        hint: `无法连接网关 ${GATEWAY}`,
      },
      { status: 502 },
    );
  }
}
