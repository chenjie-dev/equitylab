"use client";

/**
 * 双均线回测页 — 币安风格行情面板 + 净值曲线。
 */

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
  const sign = n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(2)}%`;
}

function toneClass(n: number): string {
  if (n > 0) return "up";
  if (n < 0) return "down";
  return "neutral";
}

function EquityChart({ points }: { points: EquityPoint[] }) {
  const { linePath, areaPath, minE, maxE, w, h } = useMemo(() => {
    const w = 720;
    const h = 300;
    const padX = 40;
    const padY = 20;
    if (points.length < 2) {
      return { linePath: "", areaPath: "", minE: 1, maxE: 1, w, h };
    }
    const eqs = points.map((p) => p.equity);
    const minE = Math.min(...eqs);
    const maxE = Math.max(...eqs);
    const span = maxE - minE || 0.01;
    const coords = points.map((p, i) => {
      const x = padX + (i / (points.length - 1)) * (w - padX * 2);
      const y = padY + (1 - (p.equity - minE) / span) * (h - padY * 2);
      return { x, y };
    });
    const linePath = `M ${coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" L ")}`;
    const last = coords[coords.length - 1];
    const first = coords[0];
    const areaPath = `${linePath} L ${last.x.toFixed(1)},${h - padY} L ${first.x.toFixed(1)},${h - padY} Z`;
    return { linePath, areaPath, minE, maxE, w, h };
  }, [points]);

  if (!linePath) {
    return <p className="chart-empty">运行回测后显示净值曲线</p>;
  }

  return (
    <svg
      className="equity-chart"
      viewBox={`0 0 ${w} ${h}`}
      role="img"
      aria-label="净值曲线"
    >
      <defs>
        <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#f0b90b" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#f0b90b" stopOpacity="0" />
        </linearGradient>
      </defs>
      <line x1="40" y1={h / 2} x2={w - 40} y2={h / 2} className="chart-grid" />
      <path d={areaPath} className="chart-fill" />
      <path d={linePath} className="chart-line" fill="none" />
      <text x="8" y="18" className="chart-label">
        {maxE.toFixed(3)}
      </text>
      <text x="8" y={h - 8} className="chart-label">
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
    <div className="page">
      <header className="page-head">
        <div>
          <p className="page-kicker">Strategy · dual_ma</p>
          <h1 className="page-title">双均线回测</h1>
          <p className="page-desc">
            金叉买入 / 死叉卖出。研究层拉取 market-data <code>/bars</code>
            ，输出模拟净值（非实盘）。
          </p>
        </div>
      </header>

      <div className="layout-split">
        <form className="panel" onSubmit={onSubmit}>
          <h2 className="panel-title">参数</h2>
          <div className="form-grid">
            <label className="field" style={{ gridColumn: "1 / -1" }}>
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
            <label className="field" style={{ gridColumn: "1 / -1" }}>
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
          <div style={{ marginTop: 16 }}>
            <button type="submit" className="btn-block" disabled={loading}>
              {loading ? "回测中…" : "运行回测"}
            </button>
          </div>
          {error ? <pre className="error">{error}</pre> : null}
        </form>

        <section className="panel">
          <h2 className="panel-title">净值</h2>
          {result ? (
            <>
              <div className="metrics">
                <div className="metric-cell">
                  <span className="field-label">累计收益</span>
                  <strong className={`metric-value ${toneClass(result.metrics.cum_return)}`}>
                    {pct(result.metrics.cum_return)}
                  </strong>
                </div>
                <div className="metric-cell">
                  <span className="field-label">最大回撤</span>
                  <strong className="metric-value down">
                    {pct(result.metrics.max_drawdown)}
                  </strong>
                </div>
                <div className="metric-cell">
                  <span className="field-label">成交次数</span>
                  <strong className="metric-value neutral">
                    {result.metrics.trades}
                  </strong>
                </div>
                <div className="metric-cell">
                  <span className="field-label">K 线数</span>
                  <strong className="metric-value neutral">
                    {result.metrics.bars}
                  </strong>
                </div>
              </div>
              <EquityChart points={result.equity_curve ?? []} />
              <p className="assumptions">
                {result.mode} · {result.data_source}
                {result.assumptions?.length
                  ? ` · ${result.assumptions.slice(0, 2).join(" · ")}`
                  : ""}
              </p>
            </>
          ) : (
            <EquityChart points={[]} />
          )}
        </section>
      </div>
    </div>
  );
}
