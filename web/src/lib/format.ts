/**
 * Every number in the product renders through this file.
 *
 * No inline toFixed anywhere else. That guarantees consistency across forty
 * components and makes a locale change a one-file edit rather than a hunt.
 *
 * All formatters return "--" for null/undefined/NaN rather than "0" or "NaN".
 * A missing value and a zero value mean different things, and a UI that
 * conflates them is lying quietly.
 */

const MISSING = "––"; // en-dashes: visually distinct from a minus sign

function isNil(v: unknown): v is null | undefined {
  return v === null || v === undefined || (typeof v === "number" && !Number.isFinite(v));
}

/** Integer or fixed-decimal with thousands separators. */
export function fmt(v: number | null | undefined, digits = 0): string {
  if (isNil(v)) return MISSING;
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Compact: 1.2M, 43.1k. For axis ticks and dense tiles only. */
export function compact(v: number | null | undefined, digits = 1): string {
  if (isNil(v)) return MISSING;
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${(v / 1e9).toFixed(digits)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(digits)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(digits)}k`;
  return fmt(v, abs < 10 && !Number.isInteger(v) ? digits : 0);
}

/** Fraction (0-1) to percent. Pass alreadyPercent for values already 0-100. */
export function pct(
  v: number | null | undefined,
  digits = 1,
  alreadyPercent = false,
): string {
  if (isNil(v)) return MISSING;
  const n = alreadyPercent ? v : v * 100;
  return `${n.toFixed(digits)}%`;
}

/** Percentage-point delta, always signed. +4.2pp reads unambiguously. */
export function pp(v: number | null | undefined, digits = 1): string {
  if (isNil(v)) return MISSING;
  const n = v * 100;
  return `${n >= 0 ? "+" : ""}${n.toFixed(digits)}pp`;
}

/** Currency. Compacts above $1M because a field-force P&L is read in millions. */
export function usd(v: number | null | undefined, digits = 0): string {
  if (isNil(v)) return MISSING;
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  return `${sign}$${fmt(abs, digits)}`;
}

/** Multiplier: 2.4x */
export function mult(v: number | null | undefined, digits = 2): string {
  if (isNil(v)) return MISSING;
  return `${v.toFixed(digits)}×`;
}

/** Signed number, for deltas where direction is the message. */
export function signed(v: number | null | undefined, digits = 0): string {
  if (isNil(v)) return MISSING;
  return `${v >= 0 ? "+" : ""}${fmt(v, digits)}`;
}

/** Correlation / ratio at 3dp -- statistics are quoted at 3, not 2. */
export function stat(v: number | null | undefined, digits = 3): string {
  if (isNil(v)) return MISSING;
  return v.toFixed(digits);
}

/** "SMITH, J." from parts. Surnames are upper in CMS; first names get an initial. */
export function personName(
  last: string | null | undefined,
  first: string | null | undefined,
): string {
  const l = (last ?? "").trim();
  const f = (first ?? "").trim();
  if (!l && !f) return MISSING;
  if (!f) return l;
  return `${l}, ${f.charAt(0)}.`;
}

/** Human label from a snake_case config key: "rep_cost_annual" -> "Rep cost annual". */
export function humanise(key: string): string {
  const s = key.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export const MISSING_GLYPH = MISSING;
