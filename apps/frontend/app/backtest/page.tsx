"use client";

/**
 * 双均线回测页：调研究层 /backtests/run，用 SVG 画净值曲线。
 */

import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";

type EquityPoint = {
  date: string;
  equity: number;
  close?: number;
  position?: number;
};

type BacktestResponse = {
  strategy: string;
  params: {
    fast: number;
    slow: number;
    universe: string;
    count?: number;
  };
  metrics: {
    cum_return: number;
    max_drawdown: number;
    trades: number;
    bars: number;
  };
  equity_curve: EquityPoint[];
  mode?: string;
  data_source?: string;
  assumptions?: string[];
  detail?: string;
};

function pct(n: number): string {
  return `${(n * 100).toFixed(2)}%`;
}

function EquityChart({ points }: { points: EquityPoint[] }) {
  const { path, minE, maxE, w, h } = useMemo(() => {
    const w = 720;
    const h = 280;
    const pad = 24;
    if (points.length < 2) {
      return { path: "", minE: 1, maxE: 1, w, h };
    }
    const eqs = points.map((p) => p.equity);
    const minE = Math.min(...eqs);
    const maxE = Math.max(...eqs);
    const span = maxE - minE || 0.01;
    const coords = points.map((p, i) => {
      const x = pad + (i / (points.length - 1)) * (w - pad * 2);
      const y = pad + (1 - (p.equity - minE) / span) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    return { path: `M ${coords.join(" L ")}`, minE, maxE, w, h };
  }, [points]);

  if (!path) {
    return <p className="lead">净值点不足，无法绘图。</p>;
  }

  return (
    <svg
      className="equity-chart"
      viewBox={`0 0 ${w} ${h}`}
      role="img"
      aria-label="净值曲线"
    >
      <line
        x1="24"
        y1={h / 2}
        x2={w - 24}
        y2={h / 2}
        className="chart-grid"
      />
      <path d={path} className="chart-line" fill="none" />
      <text x="24" y="18" className="chart-label">
        {maxE.toFixed(3)}
      </text>
      <text x="24" y={h - 8} className="chart-label">
        {minE.toFixed(3)}
      </text>
    </svg>
  );
}

export default function BacktestPage() {
  const [universe, setUniverse] = useState("000300.SH");
  const [fast, setFast] = useState(20);
  const [slow, setSlow] = useState(60);
  const [count, setCount] = useState(120);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/backtests/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          strategy: "dual_ma",
          universe,
          fast,
          slow,
          count,
        }),
      });
      const data = (await res.json()) as BacktestResponse;
      if (!res.ok) {
        throw new Error(data.detail ?? `backtest ${res.status}`);
      }
      setResult(data);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <span className="badge">EquityLab · Dual MA</span>
      <h1>双均线回测</h1>
      <p className="lead">
        短均线上穿长均线买入、下穿卖出。研究层拉 market-data{" "}
        <code>/bars</code>，确定性引擎输出净值曲线（模拟，非实盘）。
      </p>
      <p className="nav-links">
        <Link href="/">← 对话</Link>
      </p>

      <form className="panel" onSubmit={onSubmit}>
        <div className="form-grid">
          <label className="field">
            <span className="field-label">标的</span>
            <input
              value={universe}
              onChange={(e) => setUniverse(e.target.value)}
              required
            />
          </label>
          <label className="field">
            <span className="field-label">快均线</span>
            <input
              type="number"
              min={1}
              max={120}
              value={fast}
              onChange={(e) => setFast(Number(e.target.value))}
              required
            />
          </label>
          <label className="field">
            <span className="field-label">慢均线</span>
            <input
              type="number"
              min={2}
              max={250}
              value={slow}
              onChange={(e) => setSlow(Number(e.target.value))}
              required
            />
          </label>
          <label className="field">
            <span className="field-label">K 线根数</span>
            <input
              type="number"
              min={30}
              max={252}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              required
            />
          </label>
        </div>
        <div className="row" style={{ marginTop: 16 }}>
          <button type="submit" disabled={loading}>
            {loading ? "回测中…" : "运行回测"}
          </button>
        </div>
      </form>

      {error && <pre className="error">{error}</pre>}

      {result && (
        <section className="panel result" style={{ marginTop: 16 }}>
          <div className="metrics">
            <div>
              <span className="field-label">累计收益</span>
              <strong>{pct(result.metrics.cum_return)}</strong>
            </div>
            <div>
              <span className="field-label">最大回撤</span>
              <strong>{pct(result.metrics.max_drawdown)}</strong>
            </div>
            <div>
              <span className="field-label">成交次数</span>
              <strong>{result.metrics.trades}</strong>
            </div>
            <div>
              <span className="field-label">K 线数</span>
              <strong>{result.metrics.bars}</strong>
            </div>
          </div>
          <EquityChart points={result.equity_curve ?? []} />
          <div className="meta">
            <span>
              {result.mode} · {result.data_source}
            </span>
            {result.assumptions?.length ? (
              <span className="trace">{result.assumptions.join(" · ")}</span>
            ) : null}
          </div>
        </section>
      )}
    </main>
  );
}
