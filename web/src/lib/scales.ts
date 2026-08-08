/**
 * The decile ramps, as functions.
 *
 * These are read from CSS custom properties at module load so the ramp is
 * defined in exactly ONE place (tokens.css). A component that hard-codes a hex
 * from the ramp will drift the day the ramp is tuned; this cannot.
 */

const OPPORTUNITY_FALLBACK = [
  "#EEF3F8", "#DCE6F1", "#C4D6EA", "#A6C2E0", "#83AAD4",
  "#5F91C7", "#4176B4", "#2A5C9B", "#17437B", "#0A2C5C",
];

const VOLUME_FALLBACK = [
  "#F5F5F4", "#E7E5E4", "#D6D3D1", "#BFBBB8", "#A8A29E",
  "#8C8681", "#736D68", "#57514D", "#3D3835", "#26221F",
];

function readRamp(prefix: string, fallback: string[]): string[] {
  if (typeof window === "undefined") return fallback;
  const style = getComputedStyle(document.documentElement);
  const out: string[] = [];
  for (let i = 1; i <= 10; i++) {
    const v = style.getPropertyValue(`--${prefix}${i}`).trim();
    out.push(v || fallback[i - 1]!);
  }
  return out;
}

let opportunityRamp: string[] | null = null;
let volumeRamp: string[] | null = null;

function clampDecile(d: number | null | undefined): number {
  if (d === null || d === undefined || !Number.isFinite(d)) return 1;
  return Math.max(1, Math.min(10, Math.round(d)));
}

/** Chromatic ramp -- the ranking this project argues FOR. */
export function opportunityColor(decile: number | null | undefined): string {
  opportunityRamp ??= readRamp("d", OPPORTUNITY_FALLBACK);
  return opportunityRamp[clampDecile(decile) - 1]!;
}

/** Neutral ramp -- the industry default this project argues AGAINST. */
export function volumeColor(decile: number | null | undefined): string {
  volumeRamp ??= readRamp("v", VOLUME_FALLBACK);
  return volumeRamp[clampDecile(decile) - 1]!;
}

/**
 * Text colour that stays legible on a ramp swatch.
 * Deciles 6+ are dark enough to need light text in both ramps -- computed
 * against the actual ramp luminance rather than guessed.
 */
export function onRampText(decile: number | null | undefined): string {
  return clampDecile(decile) >= 6 ? "#FFFFFF" : "var(--ink)";
}

/** Sequential alpha for heatmap cells: one hue, lightness carries the value. */
export function heatAlpha(value: number, max: number, ceiling = 0.88): string {
  if (!Number.isFinite(value) || max <= 0) return "transparent";
  const a = Math.min(value / max, 1) * ceiling;
  return `rgba(10, 44, 92, ${a.toFixed(3)})`;
}

/** Linear scale helper -- avoids pulling d3-scale into small components. */
export function linear(
  domain: [number, number],
  range: [number, number],
): (v: number) => number {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  return (v: number) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Nice-ish rounded max for an axis, so ticks land on readable numbers. */
export function niceMax(v: number): number {
  if (!Number.isFinite(v) || v <= 0) return 1;
  const mag = 10 ** Math.floor(Math.log10(v));
  const norm = v / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * mag;
}
