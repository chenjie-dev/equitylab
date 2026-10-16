"use client";

/**
 * EquityLab 对话壳。
 * 经同源 `/api/chat` BFF 转发网关；UI 使用语义化 token（对齐 shadcn 色彩语义，未强制引入 Tailwind）。
 */

import { FormEvent, useState } from "react";

type ChatResponse = {
  agent: string;
  answer: string;
  toolResults?: unknown;
  trace?: string[];
};

const SUGGESTIONS = [
  "茅台现在多少钱？",
  "计算动量因子过去3年IC",
  "跑一个双均线策略，20/60日，沪深300",
  "帮我总结宁德时代最新研报要点",
];

export default function HomePage() {
  const [message, setMessage] = useState(SUGGESTIONS[0]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message, agent: "auto" }),
      });
      if (!res.ok) {
        const errBody = await res.text();
        throw new Error(`chat ${res.status}: ${errBody.slice(0, 200)}`);
      }
      const data = (await res.json()) as ChatResponse;
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <span className="badge">EquityLab · Agent MVP</span>
      <h1>EquityLab</h1>
      <p className="lead">
        自然语言驱动的研报问答、因子挖掘与行情查询。请求经 BFF → Rust 网关 → TypeScript
        编排图（route→plan→execute→synthesize）→ Python 研究层 / 行情服务。
      </p>
      <p className="nav-links">
        <a href="/backtest">双均线回测 →</a>
      </p>

      <div className="suggestions" role="list">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            className="chip"
            onClick={() => setMessage(s)}
          >
            {s}
          </button>
        ))}
      </div>

      <form className="panel" onSubmit={onSubmit}>
        <label className="field">
          <span className="field-label">问题</span>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="试着问：宁德时代研报要点 / 动量因子 IC / 600519.SH 报价"
          />
        </label>
        <div className="row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
          <button type="submit" disabled={loading || !message.trim()}>
            {loading ? "思考中…" : "发送"}
          </button>
        </div>
        {error ? <pre className="error">{error}</pre> : null}
        {result ? (
          <div className="result">
            <div className="meta">
              <span>agent: {result.agent}</span>
              {result.trace?.length ? (
                <span className="trace">{result.trace.join(" · ")}</span>
              ) : null}
            </div>
            <pre>{result.answer}</pre>
          </div>
        ) : null}
      </form>
    </main>
  );
}
