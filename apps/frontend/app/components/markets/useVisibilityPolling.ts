"use client";

/**
 * 页面不可见时停表；可见时按 intervalMs 触发 tick（主流行情台省电/减请求）。
 */

import { useEffect, useState } from "react";

export function usePageVisible(): boolean {
  const [visible, setVisible] = useState(() =>
    typeof document === "undefined" ? true : document.visibilityState === "visible",
  );

  useEffect(() => {
    const onVis = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  return visible;
}

/** @returns 单调递增 tick；hidden 时不涨 */
export function useVisibilityPolling(intervalMs: number): number {
  const visible = usePageVisible();
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!visible || intervalMs <= 0) return;
    const id = window.setInterval(() => setTick((n) => n + 1), intervalMs);
    return () => window.clearInterval(id);
  }, [visible, intervalMs]);

  return tick;
}
