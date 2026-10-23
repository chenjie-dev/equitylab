"use client";

/**
 * Wind 行情列表：↑↓ / j k 切换标的（输入框内不抢键）。
 */

import { useEffect } from "react";

export function useListKeyboard(
  ids: string[],
  selected: string,
  onSelect: (id: string) => void,
  enabled = true,
): void {
  useEffect(() => {
    if (!enabled || !ids.length) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.tagName === "SELECT" ||
          t.isContentEditable)
      ) {
        return;
      }
      const i = ids.indexOf(selected);
      if (e.key === "ArrowDown" || e.key === "j") {
        e.preventDefault();
        const next = ids[Math.min(ids.length - 1, Math.max(0, i) + 1)];
        if (next) onSelect(next);
      } else if (e.key === "ArrowUp" || e.key === "k") {
        e.preventDefault();
        const next = ids[Math.max(0, (i < 0 ? 0 : i) - 1)];
        if (next) onSelect(next);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ids, selected, onSelect, enabled]);
}
