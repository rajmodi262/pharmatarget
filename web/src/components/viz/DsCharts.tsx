/**
 * Exhibits for the Model Lab (src/ds). Hand-rolled SVG like the rest of the
 * app: every chart animates in once, every mark answers a hover, and nothing is
 * shown that the pipeline did not compute.
 */

import { useMemo, useRef, useState } from "react";

import { fmt, pct } from "@/lib/format";
import { useInView } from "@/lib/motion";
import type {
  CalibRow, CausalRow, CoverageRow, DriftRow, FunnelRow, GainRow, LadderRow, QiniRow, RepRow,
  UpliftDecile,
} from "@/lib/types";
import { Toggle, Tooltip, TipRow, linePath, smoothPath, svgPoint, useWidth, type Tip } from "./core";

const RULE_LABEL: Record<string, string> = {
  random: "Random", volume: "Volume (today)", momentum: "Momentum (last year's growth)",
  frontier: "Frontier opportunity", hybrid: "Hybrid 50/50 (recommended)",
  gbm_abs: "GBM: absolute growth", gbm_share_raw: "GBM: raw share change", gbm_value: "GBM: value-aligned",
};
const RULE_COLOR: Record<string, string> = {
  random: "var(--ink-faint)", volume: "var(--plum)", momentum: "var(--v6)", frontier: "var(--d5)",
  hybrid: "var(--terracotta)", gbm_abs: "var(--v8)", gbm_share_raw: "var(--mauve)", gbm_value: "var(--d8)",
};
export const ruleLabel = (r: string) => RULE_LABEL[r] ?? r;

/* ================================================================ ladder */

type LadderMetric = "value_capture" | "abs_capture" | "precision_at_k" | "ndcg_at_k";

export function LadderChart({ rows }: { rows: LadderRow[] }) {
  const [ref, inView] = useInView<HTMLDivElement>(0.25);
  const [metric, setMetric] = useState<LadderMetric>("value_capture");
  const sorted = [...rows].sort((a, b) => b[metric] - a[metric]);
  const rank = new Map(sorted.map((r, i) => [r.rule, i]));
  const max = Math.max(...rows.map((r) => (metric === "value_capture" ? r.value_capture_hi : r[metric])), 1e-9);
  const ROW = 44;
  return (
    <div ref={ref}>
      <div className="mb-4">
        <Toggle label="Metric" value={metric} onChange={setMetric} options={[
          { value: "value_capture", label: "Value capture @k (primary)" },
          { value: "abs_capture", label: "Absolute capture" },
          { value: "precision_at_k", label: "Precision@k" },
          { value: "ndcg_at_k", label: "NDCG@k" },
        ]} />
      </div>
      <div className="relative" style={{ height: rows.length * ROW }}>
        {rows.map((r) => {
          const i = rank.get(r.rule) ?? 0;
          const v = r[metric];
          const w = inView ? (v / max) * 100 : 0;
          const rec = r.rule === "hybrid";
          return (
            <div key={r.rule} className="absolute inset-x-0 grid grid-cols-[200px_1fr_74px] items-center gap-3"
              style={{ top: i * ROW, height: ROW - 8, transition: "top 700ms cubic-bezier(.65,0,.35,1)" }}>
              <span className="truncate text-small" style={{ fontWeight: rec ? 700 : 500 }}>
                {ruleLabel(r.rule)}
                {!r.passes_guardrail && <span className="ml-1.5 rounded-full px-1.5 text-[10px] font-semibold text-white"
                  style={{ background: "var(--neg)" }} title="Keeps under 90% of volume's absolute growth">fails floor</span>}
              </span>
              <span className="relative h-full overflow-hidden rounded-lg" style={{ background: "var(--rule-soft)" }}>
                <span className="absolute inset-y-0 left-0 rounded-lg" style={{
                  width: `${w}%`, transition: "width 900ms cubic-bezier(.16,1,.3,1)",
                  background: rec ? "linear-gradient(90deg, var(--terracotta), var(--terracotta-hi))" : RULE_COLOR[r.rule],
                  opacity: r.passes_guardrail ? 1 : 0.55,
                }} />
                {metric === "value_capture" && inView && (
                  <span className="absolute inset-y-[30%] rounded-full" style={{
                    left: `${(r.value_capture_lo / max) * 100}%`,
                    width: `${((r.value_capture_hi - r.value_capture_lo) / max) * 100}%`,
                    background: "var(--plum)", opacity: 0.5,
                  }} title="95% bootstrap interval" />
                )}
              </span>
              <span className="num text-right text-small font-semibold">
                {metric.includes("capture") ? pct(v) : v.toFixed(3)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ================================================================== gain */

const GAIN_RULES = ["hybrid", "gbm_value", "volume", "frontier", "momentum", "random"];

export function GainChart({ rows }: { rows: GainRow[] }) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [ref, inView] = useInView<SVGSVGElement>(0.25);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [mode, setMode] = useState<"value_gain" | "value_lift">("value_gain");
  const [zoom, setZoom] = useState(true);
  const [tip, setTip] = useState<Tip | null>(null);
  const xMax = zoom ? 0.1 : 1;
  const series = useMemo(() => GAIN_RULES.map((r) => ({
    rule: r, pts: rows.filter((g) => g.rule === r && g.fraction_targeted <= xMax + 1e-9)
      .sort((a, b) => a.fraction_targeted - b.fraction_targeted),
  })), [rows, xMax]);
  const yMax = Math.max(...series.flatMap((s) => s.pts.map((p) => p[mode])), 0.01) * 1.05;
  const h = Math.min(360, Math.max(280, width * 0.5));
  const pad = { l: 50, r: 130, t: 16, b: 44 };
  const x = (v: number) => pad.l + (v / xMax) * (width - pad.l - pad.r);
  const y = (v: number) => h - pad.b - (v / yMax) * (h - pad.t - pad.b);
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const p = svgPoint(e, svgRef.current);
    const f = ((p.x - pad.l) / (width - pad.l - pad.r)) * xMax;
    if (f <= 0 || f > xMax) { setTip(null); return; }
    setTip({ x: x(f), y: pad.t + 30, content: (
      <>
        <div className="mb-1 font-semibold">Top {pct(f, 1)} of prescribers</div>
        {series.map((s) => {
          const near = s.pts.reduce((a, b) => (Math.abs(b.fraction_targeted - f) < Math.abs(a.fraction_targeted - f) ? b : a), s.pts[0]!);
          return near ? <TipRow key={s.rule} label={ruleLabel(s.rule)} value={mode === "value_gain" ? pct(near[mode]) : `${near[mode].toFixed(1)}×`} color={RULE_COLOR[s.rule]} /> : null;
        })}
      </>) });
  };
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-3">
        <Toggle label="Curve" value={mode} onChange={setMode} options={[
          { value: "value_gain", label: "Cumulative gain" }, { value: "value_lift", label: "Lift vs random" }]} />
        <Toggle label="Zoom" value={zoom ? "z" : "f"} onChange={(v) => setZoom(v === "z")} options={[
          { value: "z", label: "Top 10%" }, { value: "f", label: "Whole market" }]} />
      </div>
      <div ref={wrap} className="relative">
        <svg ref={(el) => { svgRef.current = el; ref.current = el; }} key={`${mode}${zoom}`}
          viewBox={`0 0 ${width} ${h}`} width="100%" height={h} className={inView ? "in" : ""}
          onPointerMove={onMove} onPointerLeave={() => setTip(null)} role="img"
          aria-label="Cumulative share of value captured against share of prescribers targeted, for each rule.">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y(t * yMax)} y2={y(t * yMax)} stroke="var(--rule)" strokeDasharray="2 5" />
              <text x={pad.l - 8} y={y(t * yMax) + 4} textAnchor="end" fontSize={11} fill="var(--ink-faint)" className="num">
                {mode === "value_gain" ? pct(t * yMax, 0) : `${(t * yMax).toFixed(0)}×`}
              </text>
            </g>
          ))}
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <text key={t} x={x(t * xMax)} y={h - pad.b + 18} textAnchor="middle" fontSize={11} fill="var(--ink-faint)" className="num">
              {pct(t * xMax, zoom ? 1 : 0)}
            </text>
          ))}
          <text x={(pad.l + width - pad.r) / 2} y={h - 6} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">
            Share of prescribers targeted, best-ranked first →
          </text>
          {series.map((s, i) => {
            const pts = s.pts.map((p) => [x(p.fraction_targeted), y(p[mode])] as [number, number]);
            const last = pts[pts.length - 1];
            return (
              <g key={s.rule}>
                <path d={linePath(pts)} pathLength={1} className="draw-path" fill="none" stroke={RULE_COLOR[s.rule]}
                  strokeWidth={s.rule === "hybrid" ? 3.2 : 1.8} strokeDasharray={s.rule === "random" ? "4 4" : undefined}
                  style={{ transitionDelay: `${i * 120}ms` }} />
                {last && <text x={last[0] + 6} y={last[1] + 4} fontSize={10.5} fill={RULE_COLOR[s.rule]} fontWeight={600}
                  style={{ opacity: inView ? 1 : 0, transition: `opacity 400ms ${1200 + i * 100}ms` }}>{ruleLabel(s.rule)}</text>}
              </g>
            );
          })}
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>
    </div>
  );
}

/* =============================================================== funnel */

/** Raw vs shrunk share against observed volume: the funnel collapses on toggle. */
export function FunnelScatter({ rows }: { rows: FunnelRow[] }) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [shrunk, setShrunk] = useState(false);
  const h = Math.min(340, Math.max(260, width * 0.48));
  const pad = { l: 46, r: 16, t: 12, b: 42 };
  const maxN = Math.max(...rows.map((r) => r.class_fills_observed), 10);
  const x = (n: number) => pad.l + (Math.log10(Math.max(n, 1)) / Math.log10(maxN)) * (width - pad.l - pad.r);
  const y = (v: number) => h - pad.b - v * (h - pad.t - pad.b);
  return (
    <div>
      <div className="mb-3">
        <Toggle label="Share shown" value={shrunk ? "eb" : "raw"} onChange={(v) => setShrunk(v === "eb")} options={[
          { value: "raw", label: "Raw share" }, { value: "eb", label: "Empirical-Bayes shrunk" }]} />
      </div>
      <div ref={wrap}>
        <svg viewBox={`0 0 ${width} ${h}`} width="100%" height={h} role="img"
          aria-label="Brand share against observed class volume, raw or shrunk.">
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="var(--rule)" strokeDasharray="2 5" />
              <text x={pad.l - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--ink-faint)" className="num">{pct(t, 0)}</text>
            </g>
          ))}
          {[1, 10, 100, 1000].filter((n) => n <= maxN).map((n) => (
            <text key={n} x={x(n)} y={h - pad.b + 18} textAnchor="middle" fontSize={11} fill="var(--ink-faint)" className="num">{n}</text>
          ))}
          <text x={(pad.l + width - pad.r) / 2} y={h - 6} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">
            Observed class fills (log) — the denominator of share →
          </text>
          {rows.map((r, i) => (
            <circle key={i} cx={x(r.class_fills_observed)} cy={y(shrunk ? r.eb_share : r.raw_share)} r={2.4}
              fill={shrunk ? "var(--terracotta)" : "var(--mauve)"} opacity={0.55}
              style={{ transition: `cy 900ms cubic-bezier(.65,0,.35,1) ${(i % 60) * 6}ms, fill 600ms` }} />
          ))}
        </svg>
      </div>
    </div>
  );
}

/* ============================================================= coverage */

export function CoveragePlot({ rows, target = 0.9 }: { rows: CoverageRow[]; target?: number }) {
  const variants = [...new Set(rows.map((r) => r.variant))];
  const [variant, setVariant] = useState(variants.find((v) => v.includes("out-of-time, conformal")) ?? variants[0]!);
  const [ref, inView] = useInView<HTMLDivElement>(0.25);
  const sel = rows.filter((r) => r.variant === variant && ["all", "size_band", "rural", "specialty_group"].includes(r.segment));
  const lo = 0.8;
  const hi = 1.0;
  const xp = (v: number) => `${((Math.min(Math.max(v, lo), hi) - lo) / (hi - lo)) * 100}%`;
  return (
    <div ref={ref}>
      <div className="mb-3">
        <Toggle label="Variant" value={variant} onChange={setVariant}
          options={variants.map((v) => ({ value: v, label: v.replace("out-of-time, ", "out-of-time · ") }))} />
      </div>
      <div className="relative space-y-1.5">
        <div className="pointer-events-none absolute inset-y-0" style={{ left: `calc(170px + (100% - 170px - 64px) * ${(target - lo) / (hi - lo)})`, width: 0, borderLeft: "2px dashed var(--pos)" }} />
        {sel.map((r, i) => (
          <div key={`${r.segment}${r.level}`} className="grid grid-cols-[170px_1fr_64px] items-center gap-2 text-small">
            <span className="truncate text-ink-mute">{r.segment === "all" ? <strong className="text-ink">All prescribers</strong> : `${r.segment.replace("_", " ")} · ${r.level}`}</span>
            <span className="relative h-3">
              <span className="absolute top-1/2 h-px w-full" style={{ background: "var(--rule)" }} />
              <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{
                left: inView ? xp(r.coverage) : "0%",
                background: r.coverage >= target - 0.005 ? "var(--pos)" : r.coverage >= target - 0.03 ? "var(--warn)" : "var(--neg)",
                transition: `left 800ms cubic-bezier(.16,1,.3,1) ${i * 30}ms`,
              }} title={`n = ${fmt(r.n)}, median width ${fmt(r.median_width)} fills`} />
            </span>
            <span className="num text-right font-semibold">{pct(r.coverage, 1)}</span>
          </div>
        ))}
        <div className="grid grid-cols-[170px_1fr_64px] gap-2 text-[10px] text-ink-faint">
          <span />
          <span className="flex justify-between"><span>80%</span><span style={{ color: "var(--pos)" }}>target 90%</span><span>100%</span></span>
        </div>
      </div>
    </div>
  );
}

/* ========================================================== reliability */

export function Reliability({ rows, kind }: { rows: CalibRow[]; kind: "count" | "prob" }) {
  const [wrap, width] = useWidth<HTMLDivElement>(400);
  const [ref, inView] = useInView<SVGSVGElement>(0.3);
  const h = Math.min(300, Math.max(240, width * 0.7));
  const pad = { l: 46, r: 12, t: 12, b: 40 };
  const m = Math.max(...rows.flatMap((r) => [r.mean_pred, r.mean_actual]), 1e-9);
  const lg = (v: number) => (kind === "count" ? Math.log10(Math.max(v, 1)) / Math.log10(m) : v / Math.max(m, 1));
  const x = (v: number) => pad.l + lg(v) * (width - pad.l - pad.r);
  const y = (v: number) => h - pad.b - lg(v) * (h - pad.t - pad.b);
  return (
    <div ref={wrap}>
      <svg ref={ref} viewBox={`0 0 ${width} ${h}`} width="100%" height={h} className={inView ? "in" : ""} role="img"
        aria-label="Predicted against actual, by decile of prediction.">
        <line x1={x(kind === "count" ? 1 : 0)} y1={y(kind === "count" ? 1 : 0)} x2={x(m)} y2={y(m)} stroke="var(--ink-faint)" strokeDasharray="4 4" />
        <path d={smoothPath(rows.map((r) => [x(r.mean_pred), y(r.mean_actual)]))} pathLength={1} className="draw-path"
          fill="none" stroke="var(--terracotta)" strokeWidth={2.6} />
        {rows.map((r) => <circle key={r.bin} cx={x(r.mean_pred)} cy={y(r.mean_actual)} r={4} fill="var(--terracotta)" stroke="var(--panel)" strokeWidth={1.5} />)}
        <text x={(pad.l + width - pad.r) / 2} y={h - 6} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">
          {kind === "count" ? "Predicted fills (log)" : "Predicted probability"} →
        </text>
        <text transform={`translate(12 ${(pad.t + h - pad.b) / 2}) rotate(-90)`} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">
          Actual →
        </text>
      </svg>
    </div>
  );
}

/* ======================================================= representation */

export function Representation({ rows }: { rows: RepRow[] }) {
  const [seg, setSeg] = useState("specialty_group");
  const [ref, inView] = useInView<HTMLDivElement>(0.25);
  const sel = rows.filter((r) => r.segment === seg).sort((a, b) => b.share_of_value - a.share_of_value);
  const max = Math.max(...sel.flatMap((r) => [r.share_of_list, r.share_of_value]), 0.01);
  return (
    <div ref={ref}>
      <div className="mb-3">
        <Toggle label="Segment" value={seg} onChange={setSeg} options={[
          { value: "specialty_group", label: "Specialty" }, { value: "size_band", label: "Size" },
          { value: "region", label: "Region" }, { value: "rural", label: "Rural / urban" }]} />
      </div>
      <div className="space-y-2.5">
        {sel.map((r, i) => (
          <div key={r.level} className="grid grid-cols-[150px_1fr_60px] items-center gap-3 text-small">
            <span className="truncate">{r.level}</span>
            <span className="space-y-1">
              {(["share_of_value", "share_of_list"] as const).map((k) => (
                <span key={k} className="block h-2.5 rounded-full" style={{
                  width: inView ? `${(r[k] / max) * 100}%` : 0,
                  background: k === "share_of_value" ? "var(--mauve)" : "var(--terracotta)",
                  transition: `width 800ms cubic-bezier(.16,1,.3,1) ${i * 60}ms`,
                }} title={`${k === "share_of_value" ? "Share of realised value" : "Share of the 60-rep list"}: ${pct(r[k])}`} />
              ))}
            </span>
            <span className="num text-right font-semibold" style={{
              color: r.representation_ratio < 0.8 ? "var(--neg)" : r.representation_ratio > 1.25 ? "var(--warn)" : "var(--pos)" }}>
              {r.representation_ratio.toFixed(2)}×
            </span>
          </div>
        ))}
      </div>
      <p className="mt-3 flex gap-4 text-micro text-ink-mute normal-case tracking-normal">
        <span><span className="mr-1 inline-block h-2 w-3 rounded-full" style={{ background: "var(--mauve)" }} />share of realised value</span>
        <span><span className="mr-1 inline-block h-2 w-3 rounded-full" style={{ background: "var(--terracotta)" }} />share of the 60-rep list</span>
        <span>ratio = list ÷ value</span>
      </p>
    </div>
  );
}

/* ============================================================== forest */

export function ForestPlot({ rows }: { rows: CausalRow[] }) {
  const [ref, inView] = useInView<HTMLDivElement>(0.3);
  const shown = rows.filter((r) => r.treatment.startsWith("any"));
  const vals = shown.flatMap((r) => [r.theta, r.ci_low ?? r.theta, r.ci_high ?? r.theta]).map((v) => v * 100);
  const lo = Math.min(0, ...vals) - 0.2;
  const hi = Math.max(...vals) + 0.2;
  const xp = (v: number) => `${((v * 100 - lo) / (hi - lo)) * 100}%`;
  return (
    <div ref={ref} className="space-y-4">
      <div className="relative grid grid-cols-[200px_1fr_120px] gap-3 text-[10px] text-ink-faint">
        <span /><span className="relative h-3">
          <span className="absolute -translate-x-1/2" style={{ left: xp(0) }}>0</span>
        </span><span />
      </div>
      {shown.map((r, i) => (
        <div key={r.spec} className="grid grid-cols-[200px_1fr_120px] items-center gap-3 text-small">
          <span className={i === shown.length - 1 ? "font-semibold" : "text-ink-mute"}>{r.spec}</span>
          <span className="relative h-5">
            <span className="absolute inset-y-0 w-px" style={{ left: xp(0), background: "var(--ink-faint)" }} />
            {r.ci_low != null && r.ci_high != null && (
              <span className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full" style={{
                left: xp(r.ci_low), width: inView ? `calc(${xp(r.ci_high)} - ${xp(r.ci_low)})` : 0,
                background: "var(--terracotta)", opacity: 0.45, transition: `width 700ms ${i * 150}ms`,
              }} />
            )}
            <span className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{
              left: inView ? xp(r.theta) : xp(0), transition: `left 800ms cubic-bezier(.16,1,.3,1) ${i * 150}ms`,
              background: i === shown.length - 1 ? "var(--terracotta)" : "var(--mauve)",
            }} />
          </span>
          <span className="num text-right font-semibold">
            {(r.theta * 100).toFixed(2)} pts{r.ci_low != null ? ` ±${(((r.ci_high ?? 0) - (r.ci_low ?? 0)) * 50).toFixed(2)}` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ================================================================ qini */

export function QiniChart({ rows }: { rows: QiniRow[] }) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [ref, inView] = useInView<SVGSVGElement>(0.3);
  const h = Math.min(300, Math.max(240, width * 0.5));
  const pad = { l: 50, r: 16, t: 14, b: 42 };
  const yMax = Math.max(...rows.flatMap((r) => [r.uplift_model, r.uplift_random]), 0.01) * 1.08;
  const yMin = Math.min(0, ...rows.map((r) => r.uplift_model));
  const x = (v: number) => pad.l + v * (width - pad.l - pad.r);
  const y = (v: number) => h - pad.b - ((v - yMin) / (yMax - yMin)) * (h - pad.t - pad.b);
  const model = rows.map((r) => [x(r.fraction_targeted), y(r.uplift_model)] as [number, number]);
  const area = `${linePath(model)} L${x(1)} ${y(rows[rows.length - 1]?.uplift_random ?? 0)} L${x(0)} ${y(0)} Z`;
  return (
    <div ref={wrap}>
      <svg ref={ref} viewBox={`0 0 ${width} ${h}`} width="100%" height={h} className={inView ? "in" : ""} role="img"
        aria-label="Qini curve: cumulative uplift captured against share targeted, model against random.">
        <path d={area} fill="var(--terracotta)" opacity={inView ? 0.12 : 0} style={{ transition: "opacity 900ms 900ms" }} />
        <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(rows[rows.length - 1]?.uplift_random ?? 0)} stroke="var(--ink-faint)" strokeDasharray="5 4" />
        <path d={linePath(model)} pathLength={1} className="draw-path" fill="none" stroke="var(--terracotta)" strokeWidth={3} />
        {[0, 0.5, 1].map((t) => (
          <text key={t} x={x(t)} y={h - pad.b + 18} textAnchor="middle" fontSize={11} fill="var(--ink-faint)" className="num">{pct(t, 0)}</text>
        ))}
        <text x={(pad.l + width - pad.r) / 2} y={h - 6} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">Share targeted, by predicted uplift →</text>
        <text x={x(0.55)} y={y(rows[Math.floor(rows.length * 0.55)]?.uplift_random ?? 0) + 16} fontSize={10.5} fill="var(--ink-mute)">random</text>
      </svg>
    </div>
  );
}

export function DecileStairs({ rows, unit }: { rows: UpliftDecile[]; unit: string }) {
  const [ref, inView] = useInView<HTMLDivElement>(0.3);
  const max = Math.max(...rows.map((r) => Math.abs(r.observed) + 2 * r.se), 1e-9);
  return (
    <div ref={ref} className="flex h-[220px] items-center gap-1.5">
      {rows.map((r, i) => {
        const hgt = (Math.abs(r.observed) / max) * 50;
        const up = r.observed >= 0;
        return (
          <div key={r.decile} className="relative flex h-full flex-1 flex-col items-center" title={`Decile ${r.decile}: observed ${r.observed.toFixed(2)} ${unit} (±${(2 * r.se).toFixed(2)}), predicted ${r.predicted.toFixed(2)}`}>
            <div className="relative h-full w-full">
              <div className="absolute inset-x-0 top-1/2 h-px" style={{ background: "var(--ink-faint)" }} />
              <div className="absolute inset-x-1 rounded" style={{
                top: up ? `${50 - (inView ? hgt : 0)}%` : "50%", height: `${inView ? hgt : 0}%`,
                background: up ? (r.decile >= 9 ? "var(--terracotta)" : "var(--d4)") : "var(--mauve)",
                transition: `all 700ms cubic-bezier(.16,1,.3,1) ${i * 60}ms`,
              }} />
            </div>
            <span className="num text-[10px] text-ink-faint">{r.decile}</span>
          </div>
        );
      })}
    </div>
  );
}

/* ================================================================ bars */

export function HBars({ rows, value, label, fmtV, color = "var(--terracotta)", signed = false }: {
  rows: Record<string, unknown>[];
  value: string;
  label: string;
  fmtV: (v: number) => string;
  color?: string;
  signed?: boolean;
}) {
  const [ref, inView] = useInView<HTMLDivElement>(0.3);
  const vals = rows.map((r) => Number(r[value]));
  const max = Math.max(...vals.map(Math.abs), 1e-9);
  return (
    <div ref={ref} className="space-y-2">
      {rows.map((r, i) => {
        const v = Number(r[value]);
        const w = (Math.abs(v) / max) * (signed ? 50 : 100);
        return (
          <div key={String(r[label])} className="grid grid-cols-[minmax(150px,240px)_1fr_70px] items-center gap-3 text-small">
            <span className="truncate">{String(r[label])}</span>
            <span className="relative h-3 rounded-full" style={{ background: "var(--rule-soft)" }}>
              {signed && <span className="absolute inset-y-[-3px] left-1/2 w-px" style={{ background: "var(--ink-faint)" }} />}
              <span className="absolute inset-y-0 rounded-full" style={{
                left: signed ? (v >= 0 ? "50%" : `${50 - (inView ? w : 0)}%`) : 0,
                width: `${inView ? w : 0}%`,
                background: signed ? (v >= 0 ? "var(--pos)" : "var(--neg)") : color,
                transition: `all 800ms cubic-bezier(.16,1,.3,1) ${i * 60}ms`,
              }} />
            </span>
            <span className="num text-right font-semibold">{fmtV(v)}</span>
          </div>
        );
      })}
    </div>
  );
}

/* =============================================================== drift */

export function DriftHeat({ rows }: { rows: DriftRow[] }) {
  const pairs = [...new Set(rows.map((r) => `${r.from_year}→${r.to_year}`))];
  const feats = [...new Set(rows.map((r) => r.feature))];
  const get = (f: string, p: string) => rows.find((r) => r.feature === f && `${r.from_year}→${r.to_year}` === p);
  const color = (v: number) => (v < 0.1 ? `rgba(76,125,90,${0.15 + v * 4})` : v < 0.25 ? "var(--warn)" : "var(--neg)");
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] border-separate text-small" style={{ borderSpacing: 3 }}>
        <thead>
          <tr><th className="eyebrow text-left">Input</th>{pairs.map((p) => <th key={p} className="eyebrow text-center">{p}</th>)}</tr>
        </thead>
        <tbody>
          {feats.map((f) => (
            <tr key={f}>
              <td className="py-0.5 text-ink-mute">{f}{get(f, pairs[0]!)?.is_score ? <strong className="ml-1 text-ink">(score)</strong> : null}</td>
              {pairs.map((p) => {
                const r = get(f, p);
                return (
                  <td key={p} className="num rounded px-2 py-1 text-center text-[12px]" style={{ background: r ? color(r.psi) : undefined }}
                    title={r ? `PSI ${r.psi.toFixed(4)}${r.ks != null ? ` · KS ${r.ks.toFixed(3)}` : ""}` : ""}>
                    {r ? r.psi.toFixed(3) : "–"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
