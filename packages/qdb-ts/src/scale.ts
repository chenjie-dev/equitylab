export const PRICE_SCALE = 10_000;

export function scale(value: number): number {
  return Math.round(value * PRICE_SCALE);
}

export function unscale(raw: string | number | undefined | null): number {
  if (raw == null || raw === "") return 0;
  const n = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(n)) return 0;
  return n / PRICE_SCALE;
}
