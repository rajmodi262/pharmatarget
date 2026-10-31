/**
 * Shared machinery for the interactive exhibits: a responsive frame, a pointer
 * tooltip, a ring gauge, a labelled slider and toggle chips.
 *
 * Charts stay hand-rolled SVG (see components/charts/Charts.tsx for why). What
 * changes here is that every exhibit now answers the reader's next question
 * itself -- hover for the value, drag for the scenario -- instead of leaving
 * it for a follow-up meeting.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

import { useTween } from "@/lib/motion";

/* ----------------------------------------------------------- frame width */

/** Measured width of a container, so SVG viewBoxes match real pixels. */
export function useWidth<T extends HTMLElement>(fallback = 640) {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => {
      if (e) setW(Math.max(280, Math.round(e.contentRect.width)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

/* --------------------------------------------------------------- tooltip */

export interface Tip {
  x: number;
  y: number;
  content: ReactNode;
}

/** Positioned inside a `relative` parent; flips left near the right edge. */
export function Tooltip({ tip, width }: { tip: Tip | null; width: number }) {
  if (!tip) return null;
  const flip = tip.x > width * 0.62;
  return (
    <div
      className="pointer-events-none absolute z-20 rounded-lg px-3 py-2 text-small shadow-lg"
      style={{
        left: tip.x,
        top: tip.y,
        transform: `translate(${flip ? "calc(-100% - 14px)" : "14px"}, -50%)`,
        background: "var(--plum)",
        color: "var(--text-hi)",
        border: "1px solid rgba(248,238,234,.12)",
        minWidth: 150,
        transition: "left 90ms linear, top 90ms linear",
      }}
    >
      {tip.content}
    </div>
  );
}

export function TipRow({ label, value, color }: {
  label: string;
  value: ReactNode;
  color?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 leading-6">
      <span className="flex items-center gap-1.5" style={{ color: "var(--text-mute)" }}>
        {color && <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />}
        {label}
      </span>
      <span className="num font-medium">{value}</span>
    </div>
  );
}

/* ------------------------------------------------------------ ring gauge */

/** Animated 0-1 ring with the value in the centre. */
export function Ring({ value, label, size = 128, color = "var(--terracotta)", threshold }: {
  value: number;
  label: ReactNode;
  size?: number;
  color?: string;
  threshold?: number;
}) {
  const v = useTween(Math.max(0, Math.min(1, value)), 600);
  const r = size / 2 - 9;
  const c = 2 * Math.PI * r;
  const tAngle = threshold != null ? threshold * 2 * Math.PI - Math.PI / 2 : null;
  return (
    <div className="relative inline-grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--rule)" strokeWidth={9} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={9}
          strokeLinecap="round" strokeDasharray={`${v * c} ${c}`}
        />
      </svg>
      {tAngle != null && (
        <span
          className="absolute h-3 w-[2px] rounded"
          style={{
            background: "var(--ink)",
            left: size / 2 + Math.cos(tAngle) * r - 1,
            top: size / 2 + Math.sin(tAngle) * r - 6,
            transform: `rotate(${tAngle + Math.PI / 2}rad)`,
          }}
          title={`Threshold ${(threshold! * 100).toFixed(0)}%`}
        />
      )}
      <div className="absolute inset-0 grid place-items-center text-center">
        <div>
          <div className="num text-[26px] font-semibold leading-none">{(v * 100).toFixed(0)}%</div>
          <div className="eyebrow mt-1 !text-[9px]">{label}</div>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- slider */

export function Slider({ label, value, min, max, step, onChange, display, marks }: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  display: string;
  marks?: { at: number; label: string }[];
}) {
  const fill = ((value - min) / (max - min || 1)) * 100;
  return (
    <label className="block">
      <span className="flex items-baseline justify-between">
        <span className="eyebrow">{label}</span>
        <span className="num text-small font-semibold" style={{ color: "var(--terracotta)" }}>
          {display}
        </span>
      </span>
      <input
        type="range"
        className="range mt-1"
        min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ ["--fill" as string]: `${fill}%` }}
        aria-label={label}
      />
      {marks && (
        <span className="relative block h-4">
          {marks.map((m) => (
            <button
              key={m.label}
              type="button"
              onClick={(e) => { e.preventDefault(); onChange(m.at); }}
              className="absolute -translate-x-1/2 whitespace-nowrap text-[10px] text-ink-faint hover:text-terracotta"
              style={{ left: `${((m.at - min) / (max - min || 1)) * 100}%` }}
            >
              ▲ {m.label}
            </button>
          ))}
        </span>
      )}
    </label>
  );
}

/* ---------------------------------------------------------- toggle chips */

export function Toggle<T extends string>({ options, value, onChange, label }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className="chip"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- utilities */

/** Standard normal CDF (Abramowitz-Stegun 7.1.26, |error| < 1.5e-7). */
export function normCdf(x: number): number {
  const t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t
    + 0.254829592) * t * Math.exp(-(x * x) / 2);
  return x >= 0 ? (1 + y) / 2 : (1 - y) / 2;
}

/** SVG path through points. */
export function linePath(pts: [number, number][]): string {
  return pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
}

/** Smooth path (Catmull-Rom -> cubic Bezier) for curves that are continuous. */
export function smoothPath(pts: [number, number][]): string {
  if (pts.length < 3) return linePath(pts);
  let d = `M${pts[0]![0].toFixed(1)} ${pts[0]![1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i]!;
    const p1 = pts[i]!;
    const p2 = pts[i + 1]!;
    const p3 = pts[i + 2] ?? p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}

export function svgPoint(e: React.PointerEvent<SVGElement>, svg: SVGSVGElement | null) {
  const r = svg?.getBoundingClientRect();
  return r ? { x: e.clientX - r.left, y: e.clientY - r.top } : { x: 0, y: 0 };
}

/** Last element (Array.prototype.at is past this project's ES target). */
export function last<T>(a: readonly T[]): T | undefined {
  return a[a.length - 1];
}
