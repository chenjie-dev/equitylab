"use client";

/**
 * 币安风格深度图：累计买卖盘面积曲线。
 */

type Level = [string, string];

type Props = {
  bids: Level[];
  asks: Level[];
  height?: number;
};

export function DepthChart({ bids, asks, height = 160 }: Props) {
  const bidPts = accumulate(bids, "bid");
  const askPts = accumulate(asks, "ask");
  const all = [...bidPts, ...askPts];
  if (all.length < 2) {
    return (
      <div className="bn-depth-chart bn-depth-empty" style={{ height }}>
        No depth data
      </div>
    );
  }

  const minP = Math.min(...all.map((p) => p.price));
  const maxP = Math.max(...all.map((p) => p.price));
  const maxT = Math.max(...all.map((p) => p.total), 1e-12);
  const w = 600;
  const h = height;
  const pad = 4;

  const x = (price: number) =>
    pad + ((price - minP) / (maxP - minP || 1)) * (w - pad * 2);
  const y = (total: number) => h - pad - (total / maxT) * (h - pad * 2);

  const bidPath = areaPath(bidPts, x, y, h - pad, true);
  const askPath = areaPath(askPts, x, y, h - pad, false);

  const mid =
    bidPts.length && askPts.length
      ? (bidPts[bidPts.length - 1].price + askPts[0].price) / 2
      : null;

  return (
    <div className="bn-depth-chart">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" width="100%" height={height}>
        <path d={bidPath} fill="rgba(14, 203, 129, 0.22)" stroke="#0ecb81" strokeWidth="1.5" />
        <path d={askPath} fill="rgba(246, 70, 93, 0.22)" stroke="#f6465d" strokeWidth="1.5" />
        {mid != null ? (
          <line
            x1={x(mid)}
            x2={x(mid)}
            y1={pad}
            y2={h - pad}
            stroke="#474d57"
            strokeDasharray="3 3"
          />
        ) : null}
      </svg>
    </div>
  );
}

type Pt = { price: number; total: number };

function accumulate(levels: Level[], side: "bid" | "ask"): Pt[] {
  const sorted =
    side === "bid"
      ? [...levels].sort((a, b) => Number(b[0]) - Number(a[0]))
      : [...levels].sort((a, b) => Number(a[0]) - Number(b[0]));
  let acc = 0;
  const out: Pt[] = [];
  for (const [p, q] of sorted.slice(0, 40)) {
    acc += Number(q);
    out.push({ price: Number(p), total: acc });
  }
  if (side === "bid") out.reverse();
  return out;
}

function areaPath(
  pts: Pt[],
  x: (p: number) => number,
  y: (t: number) => number,
  baseY: number,
  _isBid: boolean,
): string {
  if (!pts.length) return "";
  const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.price)},${y(p.total)}`).join(" ");
  const first = pts[0];
  const last = pts[pts.length - 1];
  return `${line} L${x(last.price)},${baseY} L${x(first.price)},${baseY} Z`;
}
