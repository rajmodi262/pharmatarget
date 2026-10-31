/**
 * The blend frontier: every opportunity/volume weighting as one point, share
 * gain against absolute growth kept, in the year the weight was CHOSEN and the
 * year it was TESTED.
 *
 * The drift arrow between the two curves is the exhibit. It shows why a weight
 * tuned to sit exactly on the floor in one year falls through it the next --
 * and why the equal-weight blend, which had a margin, did not.
 */

import { useMemo, useRef, useState } from "react";

import { mult, pct, signed } from "@/lib/format";
import { useInView, useTween } from "@/lib/motion";
import { linear } from "@/lib/scales";
import type { FrontierRow } from "@/lib/types";
import { Ring, Slider, Tooltip, TipRow, smoothPath, svgPoint, useWidth, last, type Tip } from "./core";

export function FrontierChart({ rows, floor = 0.9, recommended = 0.5, tuned }: {
  rows: FrontierRow[];
  floor?: number;
  recommended?: number;
  tuned?: number | null;
}) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [ref, inView] = useInView<SVGSVGElement>(0.25);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [weight, setWeight] = useState(recommended);
  const [tip, setTip] = useState<Tip | null>(null);

  const sel = useMemo(() => rows.filter((r) => r.period === "selection"), [rows]);
  const hold = useMemo(() => rows.filter((r) => r.period === "holdout"), [rows]);

  const h = Math.min(440, Math.max(320, width * 0.62));
  const pad = { l: 56, r: 24, t: 28, b: 50 };
  const allAbs = rows.map((r) => r.abs_vs_volume);
  const allShare = rows.map((r) => r.share_vs_volume);
  const x = linear([Math.min(...allAbs, 0.74) - 0.01, 1.01], [pad.l, width - pad.r]);
  const y = linear([0.97, Math.max(...allShare, 1.4) + 0.03], [h - pad.b, pad.t]);

  const near = (list: FrontierRow[], w: number) =>
    list.reduce((a, b) => (Math.abs(b.weight - w) < Math.abs(a.weight - w) ? b : a), list[0]!);
  const ph = hold.length ? near(hold, weight) : null;
  const ps = sel.length ? near(sel, weight) : null;

  // Tweened marker positions, so the slider glides along the curve.
  const hx = useTween(ph ? x(ph.abs_vs_volume) : 0, 450);
  const hy = useTween(ph ? y(ph.share_vs_volume) : 0, 450);
  const sx = useTween(ps ? x(ps.abs_vs_volume) : 0, 450);
  const sy = useTween(ps ? y(ps.share_vs_volume) : 0, 450);

  if (!hold.length) return null;

  const holdPath = smoothPath(hold.map((r) => [x(r.abs_vs_volume), y(r.share_vs_volume)]));
  const selPath = smoothPath(sel.map((r) => [x(r.abs_vs_volume), y(r.share_vs_volume)]));
  const fx = x(floor);

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const p = svgPoint(e, svgRef.current);
    const best = hold.reduce((a, b) =>
      Math.hypot(x(b.abs_vs_volume) - p.x, y(b.share_vs_volume) - p.y)
        < Math.hypot(x(a.abs_vs_volume) - p.x, y(a.share_vs_volume) - p.y) ? b : a);
    const d = Math.hypot(x(best.abs_vs_volume) - p.x, y(best.share_vs_volume) - p.y);
    if (d > 40) { setTip(null); return; }
    setTip({
      x: x(best.abs_vs_volume), y: y(best.share_vs_volume),
      content: (
        <>
          <div className="mb-1 font-semibold">{(best.weight * 100).toFixed(0)}% opportunity weight</div>
          <TipRow label="Share gain vs volume" value={mult(best.share_vs_volume)} />
          <TipRow label="Absolute growth kept" value={pct(best.abs_vs_volume)} />
          <TipRow label="P(clears floor)" value={pct(best.p_clears_floor, 0)} />
          <TipRow label="Net branded fills" value={signed(best.net_brand_fill_growth)} />
        </>
      ),
    });
  };

  const pClear = ph?.p_clears_floor ?? 0;
  const xt = [0.75, 0.8, 0.85, 0.9, 0.95, 1.0].filter((t) => x(t) >= pad.l - 1);
  const yt = [1.0, 1.1, 1.2, 1.3, 1.4];

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_260px]">
      <div ref={wrap} className="relative">
        <svg
          ref={(el) => { svgRef.current = el; ref.current = el; }}
          viewBox={`0 0 ${width} ${h}`}
          width="100%"
          height={h}
          className={inView ? "in" : ""}
          onPointerMove={onMove}
          onPointerLeave={() => setTip(null)}
          role="img"
          aria-label="Blend frontier: share-growth gain against absolute growth kept, for every opportunity weight, in the selection and holdout years."
        >
          <defs>
            <pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="7" stroke="var(--neg)" strokeOpacity=".22" strokeWidth="3" />
            </pattern>
            <linearGradient id="holdGrad" x1="0" x2="1">
              <stop offset="0" stopColor="var(--terracotta)" />
              <stop offset="1" stopColor="var(--mauve)" />
            </linearGradient>
          </defs>

          {/* The floor: anything left of it gives away too much of the base. */}
          <rect x={pad.l} y={pad.t} width={Math.max(fx - pad.l, 0)} height={h - pad.t - pad.b}
            fill="url(#hatch)" />
          <line x1={fx} x2={fx} y1={pad.t - 8} y2={h - pad.b} stroke="var(--neg)" strokeWidth={1.5}
            strokeDasharray="5 4" />
          <text x={fx - 6} y={pad.t - 12} textAnchor="end" fontSize={11} fill="var(--neg)" fontWeight={600}>
            ◂ fails the {pct(floor, 0)} floor
          </text>

          {yt.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="var(--rule)" strokeDasharray="2 5" />
              <text x={pad.l - 10} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--ink-faint)" className="num">
                {t.toFixed(1)}×
              </text>
            </g>
          ))}
          {xt.map((t) => (
            <text key={t} x={x(t)} y={h - pad.b + 20} textAnchor="middle" fontSize={11}
              fill="var(--ink-faint)" className="num">{pct(t, 0)}</text>
          ))}
          <text x={(pad.l + width - pad.r) / 2} y={h - 8} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">
            Absolute branded growth kept, vs today&apos;s volume list →
          </text>
          <text transform={`translate(14 ${(pad.t + h - pad.b) / 2}) rotate(-90)`} textAnchor="middle"
            fontSize={11} fill="var(--ink-mute)">Share-growth captured, vs volume →</text>

          {/* Bootstrap interval on the holdout curve */}
          {hold.map((r) => r.abs_vs_volume_lo != null && (
            <line key={`ci${r.weight}`} x1={x(r.abs_vs_volume_lo)} x2={x(r.abs_vs_volume_hi ?? r.abs_vs_volume)}
              y1={y(r.share_vs_volume)} y2={y(r.share_vs_volume)}
              stroke="var(--terracotta)" strokeOpacity={0.28} strokeWidth={6} strokeLinecap="round" />
          ))}

          <path d={selPath} fill="none" stroke="var(--mauve)" strokeWidth={2} strokeDasharray="5 4"
            style={{ opacity: inView ? 0.95 : 0, transition: "opacity 900ms 900ms" }} />
          <path d={holdPath} pathLength={1} className="draw-path" fill="none" stroke="url(#holdGrad)" strokeWidth={3} />

          {hold.map((r, i) => (
            <circle key={r.weight} cx={x(r.abs_vs_volume)} cy={y(r.share_vs_volume)} r={3.2}
              fill={r.clears_floor ? "var(--terracotta)" : "var(--panel)"}
              stroke="var(--terracotta)" strokeWidth={1.4}
              style={{ opacity: inView ? 1 : 0, transition: `opacity 400ms ${600 + i * 40}ms` }} />
          ))}

          {/* Named anchors */}
          <Anchor x={x(1)} y={y(1)} label="Volume (today)" dy={18} />
          {last(hold) && <Anchor x={x(last(hold)!.abs_vs_volume)} y={y(last(hold)!.share_vs_volume)}
            label="Opportunity only" dy={-14} />}
          {tuned != null && (() => {
            const t = near(hold, tuned);
            const s = near(sel, tuned);
            return (
              <g>
                <line x1={x(s.abs_vs_volume)} y1={y(s.share_vs_volume)} x2={x(t.abs_vs_volume)}
                  y2={y(t.share_vs_volume)} stroke="var(--neg)" strokeWidth={1.4} markerEnd="url(#arr)" />
                <text x={x(s.abs_vs_volume) + 8} y={y(s.share_vs_volume) - 10} fontSize={10.5} fill="var(--neg)">
                  tuned on 2022→23 ({(tuned * 100).toFixed(0)}%) — drifts through the floor
                </text>
              </g>
            );
          })()}
          <defs>
            <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
              <path d="M0 0L10 5L0 10z" fill="var(--neg)" />
            </marker>
          </defs>

          {/* The live selection: selection-year ghost, holdout marker, drift line */}
          {ph && ps && (
            <g>
              <line x1={sx} y1={sy} x2={hx} y2={hy} stroke="var(--ink-faint)" strokeDasharray="3 3" />
              <circle cx={sx} cy={sy} r={6} fill="var(--panel)" stroke="var(--mauve)" strokeWidth={2} />
              <circle cx={hx} cy={hy} r={9} fill="var(--terracotta)" className="pulse-ring" opacity={0.5} />
              <circle cx={hx} cy={hy} r={8} fill="var(--terracotta)" stroke="var(--panel)" strokeWidth={3} />
            </g>
          )}

          <g transform={`translate(${pad.l + 12} ${h - pad.b - 44})`} fontSize={11}>
            <line x2={22} y1={6} y2={6} stroke="var(--terracotta)" strokeWidth={3} />
            <text x={28} y={10} fill="var(--ink)">2023→24 holdout (the test)</text>
            <line x2={22} y1={24} y2={24} stroke="var(--mauve)" strokeWidth={2} strokeDasharray="4 3" />
            <text x={28} y={28} fill="var(--ink-mute)">2022→23 (where a weight is chosen)</text>
          </g>
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>

      <div className="flex flex-col gap-5">
        <Slider
          label="Opportunity weight in the blend"
          value={weight} min={0} max={1} step={0.05}
          onChange={setWeight}
          display={`${(weight * 100).toFixed(0)}%`}
          marks={[{ at: 0, label: "volume" }, { at: recommended, label: "50/50" }, { at: 1, label: "opp." }]}
        />
        <div className="flex items-center gap-4">
          <Ring value={pClear} label="clears floor" threshold={0.95}
            color={pClear >= 0.8 ? "var(--pos)" : pClear >= 0.5 ? "var(--warn)" : "var(--neg)"} />
          <div className="text-small text-ink-mute">
            Share of 200 bootstrap re-draws of the 2024 market in which this list keeps
            ≥ {pct(floor, 0)} of volume&apos;s absolute growth.
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-3">
          <Stat label="Share gain" value={mult(ph?.share_vs_volume)} />
          <Stat label="Growth kept" value={pct(ph?.abs_vs_volume)} />
          <Stat label="Net fills, 2024" value={signed(ph?.net_brand_fill_growth)} />
          <Stat label="Drift from 2023" value={ps && ph ? `${((ph.abs_vs_volume - ps.abs_vs_volume) * 100).toFixed(1)}pt` : "–"} />
        </dl>
      </div>
    </div>
  );
}

function Anchor({ x, y, label, dy }: { x: number; y: number; label: string; dy: number }) {
  return (
    <text x={x} y={y + dy} textAnchor="end" fontSize={10.5} fill="var(--ink-mute)" fontStyle="italic">
      {label}
    </text>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-rule px-3 py-2">
      <dt className="eyebrow !text-[9.5px]">{label}</dt>
      <dd className="num mt-0.5 text-[17px] font-semibold">{value}</dd>
    </div>
  );
}
