"use client";

/**
 * 轻量窗口虚拟列表（无第三方依赖）：只挂载可视区 ± overscan 行。
 * 可选 onVisibleRange：父层可只拉可视窗口报价，避免全表轮询。
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

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
  /** 当前渲染窗口 [start, end)（已含 overscan） */
  onVisibleRange?: (start: number, end: number) => void;
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
  onVisibleRange,
}: Props<T>) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const rangeRef = useRef<{ start: number; end: number } | null>(null);

  const onScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setScrollTop(el.scrollTop);
  }, []);

  const totalRows = items.length;
  const start =
    totalRows === 0
      ? 0
      : Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const visibleCount = Math.ceil(height / rowHeight) + overscan * 2;
  const end =
    totalRows === 0 ? 0 : Math.min(totalRows, start + visibleCount);

  useEffect(() => {
    if (!onVisibleRange) return;
    const prev = rangeRef.current;
    if (prev && prev.start === start && prev.end === end) return;
    rangeRef.current = { start, end };
    onVisibleRange(start, end);
  }, [start, end, onVisibleRange, totalRows]);

  if (!totalRows) {
    return <div className={className}>{empty}</div>;
  }

  const total = totalRows * rowHeight;
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
