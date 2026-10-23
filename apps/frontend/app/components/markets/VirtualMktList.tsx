"use client";

/**
 * 轻量窗口虚拟列表（无第三方依赖）：只挂载可视区 ± overscan 行。
 */

import { useCallback, useRef, useState, type ReactNode } from "react";

type Props<T> = {
  items: T[];
  rowHeight: number;
  /** 列表视口高度（px）；与 CSS 滚动区一致 */
  height: number;
  overscan?: number;
  keyOf: (item: T, index: number) => string;
  renderRow: (item: T, index: number) => ReactNode;
  empty?: ReactNode;
  className?: string;
};

export function VirtualMktList<T>({
  items,
  rowHeight,
  height,
  overscan = 6,
  keyOf,
  renderRow,
  empty,
  className,
}: Props<T>) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);

  const onScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setScrollTop(el.scrollTop);
  }, []);

  if (!items.length) {
    return <div className={className}>{empty}</div>;
  }

  const total = items.length * rowHeight;
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const visibleCount = Math.ceil(height / rowHeight) + overscan * 2;
  const end = Math.min(items.length, start + visibleCount);
  const offsetY = start * rowHeight;

  return (
    <div
      ref={scrollerRef}
      className={className}
      style={{ height, overflowY: "auto", position: "relative" }}
      onScroll={onScroll}
    >
      <div style={{ height: total, position: "relative" }}>
        <div style={{ transform: `translateY(${offsetY}px)` }}>
          {items.slice(start, end).map((item, i) => {
            const index = start + i;
            return (
              <div
                key={keyOf(item, index)}
                style={{ height: rowHeight, boxSizing: "border-box" }}
              >
                {renderRow(item, index)}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
