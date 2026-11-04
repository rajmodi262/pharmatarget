/**
 * Exhibit E3, interactive: what each allocation rule puts a rep in front of.
 *
 * Scrub to read all rules at one depth; zoom to the depth 60 reps can actually
 * cover, which is where the decision lives (a full-universe view flatters every
 * rule equally); switch the y-axis to class volume to see what the
 * opportunity rule gives up in exchange.
 */

import { useMemo, useRef, useState } from "react";

import { pct } from "@/lib/format";
import { useInView } from "@/lib/motion";
import type { ReachPoint } from "@/lib/types";
import { Toggle, Tooltip, TipRow, linePath, svgPoint, useWidth, last, type Tip } from "./core";

const SERIES: { rule: ReachPoint["rule"]; color: string; label: string; dash?: string; w: number }[] = [
  { rule: "opportunity", color: "var(--terracotta-ink)", label: "Opportunity", w: 3 },
  { rule: "volume", color: "var(--plum)", label: "Volume (today)", w: 2.4 },
  { rule: "geography", color: "var(--mauve-ink)", label: "Geography", dash: "5 4", w: 2 },
];

type Y = "pct_opportunity_reached" | "pct_class_volume_reached";

export function ReachViz({ points, budget }: { points: ReachPoint[]; budget?: number | null }) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [ref, inView] = useInView<SVGSVGElement>(0.25);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [zoom, setZoom] = useState<"budget" | "full">("budget");
  const [metric, setMetric] = useState<Y>("pct_opportunity_reached");
  const [scrub, setScrub] = useState<number | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);

  const xMax = zoom === "full" ? 1 : Math.max((budget ?? 0.03) * 4, 0.1);
  const bySeries = useMemo(() => SERIES.map((s) => ({
    ...s,
    pts: points.filter((p) => p.rule === s.rule && p.pct_of_universe <= xMax + 1e-9)
      .sort((a, b) => a.pct_of_universe - b.pct_of_universe),
  })), [points, xMax]);
  const yMax = Math.max(...bySeries.flatMap((s) => s.pts.map((p) => p[metric])), 0.05);

  if (points.length === 0) return null;

  const h = Math.min(380, Math.max(280, width * 0.52));
  const pad = { l: 50, r: 110, t: 18, b: 46 };
  const x = (v: number) => pad.l + (v / xMax) * (width - pad.l - pad.r);
  const y = (v: number) => h - pad.b - (v / (yMax * 1.05)) * (h - pad.t - pad.b);

  const valueAt = (pts: ReachPoint[], xv: number) => {
    if (!pts.length) return null;
    let a = pts[0]!;
    for (const p of pts) { if (p.pct_of_universe <= xv) a = p; }
    const i = pts.indexOf(a);
    const b = pts[i + 1];
    if (!b) return a[metric];
    const f = (xv - a.pct_of_universe) / (b.pct_of_universe - a.pct_of_universe || 1);
    return a[metric] + f * (b[metric] - a[metric]);
  };

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const p = svgPoint(e, svgRef.current);
    const xv = ((p.x - pad.l) / (width - pad.l - pad.r)) * xMax;
    if (xv < 0 || xv > xMax) { setScrub(null); setTip(null); return; }
    setScrub(xv);
    setTip({
      x: x(xv), y: pad.t + 40,
      content: (
        <>
          <div className="mb-1 font-semibold">Calling the top {pct(xv, 1)} of prescribers</div>
          {bySeries.map((s) => (
            <TipRow key={s.rule} label={s.label} value={pct(valueAt(s.pts, xv))} color={s.color} />
          ))}
        </>
      ),
    });
  };

  const xt = zoom === "full" ? [0, 0.25, 0.5, 0.75, 1] : [0, xMax / 4, xMax / 2, (3 * xMax) / 4, xMax];

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-3">
        <Toggle label="Zoom" value={zoom} onChange={setZoom}
          options={[{ value: "budget", label: "Zoom: the 60-rep budget" }, { value: "full", label: "Whole market" }]} />
        <Toggle label="Measure" value={metric} onChange={setMetric}
          options={[{ value: "pct_opportunity_reached", label: "Opportunity reached" },
            { value: "pct_class_volume_reached", label: "Class volume reached" }]} />
      </div>
      <div ref={wrap} className="relative">
        <svg ref={(el) => { svgRef.current = el; ref.current = el; }} key={`${zoom}${metric}`}
          viewBox={`0 0 ${width} ${h}`} width="100%" height={h} className={inView ? "in" : ""}
          onPointerMove={onMove} onPointerLeave={() => { setScrub(null); setTip(null); }}
          role="img" aria-label="Share of opportunity reached by each targeting rule against share of prescribers called.">
          {[0, 0.25, 0.5, 0.75, 1].map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y(t * yMax)} y2={y(t * yMax)} stroke="var(--rule)" strokeDasharray="2 5" />
              <text x={pad.l - 10} y={y(t * yMax) + 4} textAnchor="end" fontSize={11} fill="var(--ink-faint)" className="num">
                {pct(t * yMax, 0)}
              </text>
            </g>
          ))}
          {xt.map((t) => (
            <text key={t} x={x(t)} y={h - pad.b + 20} textAnchor="middle" fontSize={11} fill="var(--ink-faint)" className="num">
              {pct(t, zoom === "full" ? 0 : 1)}
            </text>
          ))}
          <text x={(pad.l + width - pad.r) / 2} y={h - 8} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">
            Share of prescribers called, best-ranked first →
          </text>

          {budget != null && budget <= xMax && (
            <g>
              <rect x={pad.l} y={pad.t} width={x(budget) - pad.l} height={h - pad.t - pad.b}
                fill="var(--terracotta)" opacity={0.07} />
              <line x1={x(budget)} x2={x(budget)} y1={pad.t} y2={h - pad.b} stroke="var(--terracotta)" strokeDasharray="4 3" />
              <text x={x(budget) + 6} y={pad.t + 12} fontSize={11} fill="var(--terracotta)" fontWeight={600}>
                60 reps reach {pct(budget, 1)}
              </text>
            </g>
          )}

          {bySeries.map((s, i) => {
            const pts = s.pts.map((p) => [x(p.pct_of_universe), y(p[metric])] as [number, number]);
            const end = last(pts);
            return (
              <g key={s.rule}>
                <path d={linePath(pts)} pathLength={1} className={s.dash ? "" : "draw-path"} fill="none"
                  stroke={s.color} strokeWidth={s.w} strokeDasharray={s.dash}
                  style={{ transitionDelay: `${i * 180}ms` }} />
                {end && (
                  <text x={end[0] + 8} y={end[1] + 4} fontSize={11.5} fontWeight={600} fill={s.color}
                    style={{ opacity: inView ? 1 : 0, transition: `opacity 500ms ${1300 + i * 150}ms` }}>
                    {s.label}
                  </text>
                )}
              </g>
            );
          })}

          {scrub != null && (
            <g>
              <line x1={x(scrub)} x2={x(scrub)} y1={pad.t} y2={h - pad.b} stroke="var(--ink)" strokeOpacity={0.3} />
              {bySeries.map((s) => {
                const v = valueAt(s.pts, scrub);
                return v == null ? null : (
                  <circle key={s.rule} cx={x(scrub)} cy={y(v)} r={5} fill={s.color} stroke="var(--panel)" strokeWidth={2} />
                );
              })}
            </g>
          )}
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>
    </div>
  );
}
