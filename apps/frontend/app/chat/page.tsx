"use client";

/**
 * 研究对话。经同源 `/api/chat` BFF 转发网关。
 * 首页是现货虚拟币行情，对话从顶栏进入。
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

export default function ChatPage() {
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
    <div className="page">
      <header className="page-head">
        <div>
          <p className="page-kicker">Agent workspace</p>
          <h1 className="page-title">智能研究对话</h1>
          <p className="page-desc">
            研报问答、因子与行情查询。请求经 BFF → 网关 → 编排层 → 研究 / 行情服务。
          </p>
        </div>
      </header>

      <div className="layout-split">
        <aside className="panel">
          <h2 className="panel-title">快捷指令</h2>
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
          <p className="page-desc" style={{ marginTop: 8 }}>
            也可在右侧自由输入；双均线回测见顶栏「回测」。
          </p>
        </aside>

        <form className="panel" onSubmit={onSubmit}>
          <h2 className="panel-title">提问</h2>
          <label className="field">
            <span className="field-label">Message</span>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="试着问：宁德时代研报要点 / 动量因子 IC / 600519.SH 报价"
            />
          </label>
          <div className="row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
            <button type="submit" disabled={loading || !message.trim()}>
              {loading ? "执行中…" : "发送"}
            </button>
          </div>
          {error ? <pre className="error">{error}</pre> : null}
          {result ? (
            <div className="result">
              <span className="agent-pill">agent · {result.agent}</span>
              {result.trace?.length ? (
                <span className="trace">{result.trace.join(" → ")}</span>
              ) : null}
              <pre>{result.answer}</pre>
            </div>
          ) : null}
        </form>
      </div>
    </div>
  );
}
