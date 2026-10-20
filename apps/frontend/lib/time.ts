/**
 * 行情时间：存储/接口为 UTC（unix ms 或 sec），展示用浏览器当前时区。
 * lightweight-charts 轴标签按 UTC 解读时间戳，需用 timeToLocal 再喂图。
 * @see https://tradingview.github.io/lightweight-charts/docs/time-zones
 */

/** UTC 秒 → 图表用「本地墙钟」伪 UTC 秒 */
export function timeToLocal(utcSec: number): number {
  const d = new Date(utcSec * 1000);
  return (
    Date.UTC(
      d.getFullYear(),
      d.getMonth(),
      d.getDate(),
      d.getHours(),
      d.getMinutes(),
      d.getSeconds(),
      d.getMilliseconds(),
    ) / 1000
  );
}

/** 图表伪 UTC 秒 → 真实 UTC 秒（十字光标反查原始 K 线） */
export function localToUtc(localSec: number): number {
  const d = new Date(localSec * 1000);
  const real = new Date(
    d.getUTCFullYear(),
    d.getUTCMonth(),
    d.getUTCDate(),
    d.getUTCHours(),
    d.getUTCMinutes(),
    d.getUTCSeconds(),
    d.getUTCMilliseconds(),
  );
  return Math.floor(real.getTime() / 1000);
}

/** unix 秒或毫秒 → 本地日期时间 `YYYY-MM-DD HH:mm` */
export function formatLocalDateTime(ts: number): string {
  const ms = ts > 1e12 ? ts : ts * 1000;
  const d = new Date(ms);
  if (!Number.isFinite(d.getTime())) return "—";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** unix 秒或毫秒 → 本地时分秒 */
export function formatLocalTime(ts: number): string {
  const ms = ts > 1e12 ? ts : ts * 1000;
  const d = new Date(ms);
  if (!Number.isFinite(d.getTime())) return "—";
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}
