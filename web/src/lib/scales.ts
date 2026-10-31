/**
 * The decile ramps, as functions.
 *
 * These are read from CSS custom properties at module load so the ramp is
 * defined in exactly ONE place (tokens.css). A component that hard-codes a hex
 * from the ramp will drift the day the ramp is tuned; this cannot.
 */

const OPPORTUNITY_FALLBACK = [
  "#F5E8E3", "#EFD5CB", "#E7BBAA", "#DE9D85", "#D27E61",
  "#C75A3A", "#A4442F", "#7E3330", "#5E2236", "#45193B",
];

const VOLUME_FALLBACK = [
  "#F3EEEC", "#E6DEDC", "#D5CACA", "#C0B3B5", "#A99A9E",
  "#908086", "#77686E", "#5E5157", "#463B41", "#2F272C",
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
  return `rgba(58, 31, 52, ${a.toFixed(3)})`;
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
