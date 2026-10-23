"use client";

/**
 * Wind 式报价闪烁：价变时短暂亮底（涨红/跌绿由 CSS `.wind .flash-up|down` 决定）。
 */

import { useEffect, useRef, useState } from "react";

export type FlashDir = "up" | "down" | null;

export function usePriceFlash(
  price: string | number | null | undefined,
  durationMs = 450,
): FlashDir {
  const prevRef = useRef<number | null>(null);
  const [flash, setFlash] = useState<FlashDir>(null);

  useEffect(() => {
    const next = price == null || price === "" ? NaN : Number(price);
    const prev = prevRef.current;
    if (!Number.isFinite(next)) {
      prevRef.current = null;
      return;
    }
    if (prev != null && Number.isFinite(prev) && next !== prev) {
      setFlash(next > prev ? "up" : "down");
      const id = window.setTimeout(() => setFlash(null), durationMs);
      prevRef.current = next;
      return () => window.clearTimeout(id);
    }
    prevRef.current = next;
  }, [price, durationMs]);

  return flash;
}

export function flashClass(dir: FlashDir): string {
  if (dir === "up") return "flash-up";
  if (dir === "down") return "flash-down";
  return "";
}
