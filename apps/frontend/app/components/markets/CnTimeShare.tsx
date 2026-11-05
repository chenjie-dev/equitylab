"use client";

/**
 * A 股分时：最近一个交易日的 5 分钟收盘连成面积图。
 * 价格轴按高低点自适应。昨收画虚线。没有 1 分钟盘中数据时仍用这段冷库。
 */

import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { timeToLocal } from "../../../lib/time";
import type { Kline } from "./chartIndicators";

function shanghaiDay(ms: number): string {
  return new Date(ms).toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" });
}

/** 只留最后一根所在的上海交易日。 */
export function lastSessionBars(rows: Kline[]): Kline[] {
  if (!rows.length) return [];
  const day = shanghaiDay(Number(rows[rows.length - 1][0]));
  return rows.filter((k) => shanghaiDay(Number(k[0])) === day);
}

type Props = {
  klines: Kline[];
  preClose?: number | null;
  seriesKey: string;
  note?: string;
};

export function CnTimeShare({ klines, preClose, seriesKey, note }: Props) {
  const stageRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const areaRef = useRef<ISeriesApi<"Area"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const prevRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#161a1e" },
        textColor: "#848e9c",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#1e2329" },
        horzLines: { color: "#1e2329" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#2b3139" },
      timeScale: {
        borderColor: "#2b3139",
        timeVisible: true,
        secondsVisible: false,
      },
    });
    const area = chart.addAreaSeries({
      lineWidth: 2,
      priceLineVisible: true,
      lastValueVisible: true,
    });
    const volume = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    volume.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });
    const prev = chart.addLineSeries({
      color: "#848e9c",
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      autoscaleInfoProvider: () => null,
    });
    chartRef.current = chart;
    areaRef.current = area;
    volRef.current = volume;
    prevRef.current = prev;
    return () => {
      chart.remove();
      chartRef.current = null;
      areaRef.current = null;
      volRef.current = null;
      prevRef.current = null;
    };
  }, []);

  useEffect(() => {
    const area = areaRef.current;
    const volume = volRef.current;
    const prev = prevRef.current;
    const chart = chartRef.current;
    if (!area || !volume || !prev || !chart) return;
    const rows = lastSessionBars(klines);
    const close = rows.length ? Number(rows[rows.length - 1][4]) : NaN;
    const anchor =
      preClose != null && Number.isFinite(preClose) && preClose > 0
        ? preClose
        : rows.length
          ? Number(rows[0][1])
          : NaN;
    const rising = Number.isFinite(close) && Number.isFinite(anchor) ? close >= anchor : true;
    area.applyOptions({
      lineColor: rising ? "#e53935" : "#1b8f5a",
      topColor: rising ? "rgba(229, 57, 53, 0.25)" : "rgba(27, 143, 90, 0.25)",
      bottomColor: "rgba(22, 26, 30, 0)",
    });
    area.setData(
      rows.map((k) => ({
        time: timeToLocal(Math.floor(Number(k[0]) / 1000)) as UTCTimestamp,
        value: Number(k[4]),
      })),
    );
    volume.setData(
      rows.map((k) => {
        const open = Number(k[1]);
        const px = Number(k[4]);
        return {
          time: timeToLocal(Math.floor(Number(k[0]) / 1000)) as UTCTimestamp,
          value: Number(k[5]) || 0,
          color: px >= open ? "rgba(229, 57, 53, 0.45)" : "rgba(27, 143, 90, 0.45)",
        };
      }),
    );
    if (Number.isFinite(anchor) && rows.length) {
      prev.setData(
        rows.map((k) => ({
          time: timeToLocal(Math.floor(Number(k[0]) / 1000)) as UTCTimestamp,
          value: anchor,
        })),
      );
    } else {
      prev.setData([]);
    }
    chart.timeScale().fitContent();
  }, [seriesKey, klines, preClose]);

  return (
    <div className="bn-chart-root">
      <div className="bn-ohlc-bar">
        <span className="bn-ohlc-pair">分时</span>
        <span className="bn-label">{note || "最近交易日 · 5 分钟"}</span>
      </div>
      <div className="bn-chart-stage" ref={stageRef} />
    </div>
  );
}
