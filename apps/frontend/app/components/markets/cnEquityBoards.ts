/**
 * A 股列表板块分类（同花顺启发）。
 * 北交所须先于「9→沪」；主板不含创业板 / 科创板 / 北交所。
 */

export type CnEquityBoardId =
  | "all"
  | "hs_main"
  | "chinext"
  | "star"
  | "bse"
  | "sse"
  | "szse";

export const CN_EQUITY_BOARDS: { id: CnEquityBoardId; label: string }[] = [
  { id: "all", label: "全部A股" },
  { id: "hs_main", label: "沪深主板" },
  { id: "chinext", label: "创业板" },
  { id: "star", label: "科创板" },
  { id: "bse", label: "京市A股" },
  { id: "sse", label: "沪市A股" },
  { id: "szse", label: "深市A股" },
];

/** 归一化 6 位代码。 */
export function code6(raw: string): string {
  return raw.replace(/\D/g, "").slice(-6).padStart(6, "0");
}

/** 是否北交所号段（含 92xxxx）。 */
export function isBseCode(c: string): boolean {
  return c.startsWith("4") || c.startsWith("8") || c.startsWith("92");
}

/** 创业板 300/301。 */
export function isChinext(c: string): boolean {
  return c.startsWith("300") || c.startsWith("301");
}

/** 科创板 688/689。 */
export function isStar(c: string): boolean {
  return c.startsWith("688") || c.startsWith("689");
}

/** 沪主板 600/601/603/605（不含科创）。 */
export function isSseMain(c: string): boolean {
  return (
    c.startsWith("600") ||
    c.startsWith("601") ||
    c.startsWith("603") ||
    c.startsWith("605")
  );
}

/** 深主板 000/001/002/003（不含创业板）。 */
export function isSzseMain(c: string): boolean {
  return (
    c.startsWith("000") ||
    c.startsWith("001") ||
    c.startsWith("002") ||
    c.startsWith("003")
  );
}

/**
 * 判断代码是否属于指定板块。
 *
 * @param stockCode 股票代码（可含非数字）
 * @param exchange UI 交易所：SH / SZ / BJ（可空，则按号段推断）
 * @param board 板块 id
 */
export function matchesCnEquityBoard(
  stockCode: string,
  exchange: string | undefined,
  board: CnEquityBoardId,
): boolean {
  if (board === "all") return true;
  const c = code6(stockCode);
  if (!c || c === "000000") return false;
  const ex = (exchange || "").toUpperCase();
  const bse = ex === "BJ" || isBseCode(c);

  switch (board) {
    case "chinext":
      return isChinext(c);
    case "star":
      return isStar(c);
    case "bse":
      return bse;
    case "sse":
      return !bse && (ex === "SH" || c.startsWith("5") || c.startsWith("6") || c.startsWith("9"));
    case "szse":
      return !bse && (ex === "SZ" || c.startsWith("0") || c.startsWith("3"));
    case "hs_main":
      return !bse && (isSseMain(c) || isSzseMain(c));
    default:
      return true;
  }
}
