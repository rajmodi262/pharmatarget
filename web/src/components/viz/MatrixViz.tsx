/**
 * Exhibit E1, interactive: where the two rankings disagree.
 *
 * Rows are opportunity decile, columns volume decile. The two framed regions
 * carry the argument -- prescribers the volume rule skips and prescribers it
 * over-serves -- and the metric toggle lets a reader check that the finding
 * holds when weighted by opportunity or by volume, not only by headcount.
 */

import { useMemo, useState } from "react";

import { compact, fmt, pct } from "@/lib/format";
import { useInView } from "@/lib/motion";
import type { DisagreementCell } from "@/lib/types";
import { Toggle, Tooltip, TipRow, useWidth, type Tip } from "./core";

type Metric = "hcp_count" | "opportunity" | "class_fills";

const METRIC_LABEL: Record<Metric, string> = {
  hcp_count: "Prescribers",
  opportunity: "Opportunity",
  class_fills: "Class volume",
};

export function MatrixViz({ cells }: { cells: DisagreementCell[] }) {
  const [wrap, width] = useWidth<HTMLDivElement>(560);
  const [ref, inView] = useInView<SVGSVGElement>(0.2);
  const [metric, setMetric] = useState<Metric>("hcp_count");
  const [hover, setHover] = useState<{ o: number; v: number } | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);

  const lookup = useMemo(
    () => new Map(cells.map((c) => [`${c.opportunity_decile}:${c.volume_decile}`, c])),
    [cells],
  );
  const total = useMemo(() => cells.reduce((s, c) => s + (c[metric] ?? 0), 0), [cells, metric]);
  const max = useMemo(() => Math.max(...cells.map((c) => c[metric] ?? 0), 1), [cells, metric]);

  const region = (lo: (o: number, v: number) => boolean) =>
    cells.filter((c) => lo(c.opportunity_decile, c.volume_decile))
      .reduce((s, c) => s + (c[metric] ?? 0), 0);
  const skipped = region((o, v) => o >= 7 && v <= 4);
  const over = region((o, v) => o <= 4 && v >= 7);

  if (cells.length === 0) return null;

  const pad = { l: 40, t: 12, b: 40, r: 12 };
  const side = Math.min(width - pad.l - pad.r, 520);
  const cell = side / 10;
  const h = side + pad.t + pad.b;
  const cx = (v: number) => pad.l + (v - 1) * cell;
  const cy = (o: number) => pad.t + (10 - o) * cell;

  return (
    <div>
      <div className="mb-3">
        <Toggle label="Weight cells by" value={metric} onChange={setMetric}
          options={(Object.keys(METRIC_LABEL) as Metric[]).map((m) => ({ value: m, label: METRIC_LABEL[m] }))} />
      </div>
      <div ref={wrap} className="relative">
        <svg ref={ref} viewBox={`0 0 ${width} ${h}`} width="100%" height={h} role="img"
          aria-label="Ten by ten matrix of prescribers by opportunity decile and volume decile."
          onPointerLeave={() => { setHover(null); setTip(null); }}>
          {Array.from({ length: 10 }, (_, i) => 10 - i).map((o) =>
            Array.from({ length: 10 }, (_, j) => j + 1).map((v) => {
              const c = lookup.get(`${o}:${v}`);
              const val = c?.[metric] ?? 0;
              const a = Math.sqrt(val / max);
              const dim = hover && hover.o !== o && hover.v !== v;
              const delay = ((10 - o) + (v - 1)) * 28;
              return (
                <rect
                  key={`${o}${v}`}
                  x={cx(v) + 1.5} y={cy(o) + 1.5} width={cell - 3} height={cell - 3} rx={5}
                  fill={o > v + 1 ? "var(--terracotta)" : o < v - 1 ? "var(--mauve)" : "var(--plum)"}
                  fillOpacity={0.06 + a * 0.9}
                  style={{
                    opacity: inView ? (dim ? 0.25 : 1) : 0,
                    transform: inView ? "scale(1)" : "scale(.4)",
                    transformBox: "fill-box", transformOrigin: "center",
                    transition: `opacity 260ms, transform 600ms cubic-bezier(.34,1.56,.64,1) ${inView && !hover ? delay : 0}ms`,
                  }}
                  onPointerEnter={() => {
                    setHover({ o, v });
                    setTip({
                      x: cx(v) + cell, y: cy(o) + cell / 2,
                      content: (
                        <>
                          <div className="mb-1 font-semibold">Opportunity {o} · Volume {v}</div>
                          <TipRow label="Prescribers" value={fmt(c?.hcp_count)} />
                          <TipRow label="Opportunity (fills)" value={compact(c?.opportunity)} />
                          <TipRow label="Class volume" value={compact(c?.class_fills)} />
                          <TipRow label={`Share of ${METRIC_LABEL[metric].toLowerCase()}`} value={pct(val / total)} />
                        </>
                      ),
                    });
                  }}
                />
              );
            }),
          )}

          {/* The two regions that carry the argument */}
          <rect x={cx(1)} y={cy(10)} width={cell * 4} height={cell * 4} rx={8} fill="none"
            stroke="var(--terracotta)" strokeWidth={2.5} strokeDasharray="7 4"
            style={{ opacity: inView ? 1 : 0, transition: "opacity 600ms 1100ms" }} />
          <rect x={cx(7)} y={cy(4)} width={cell * 4} height={cell * 4} rx={8} fill="none"
            stroke="var(--plum)" strokeWidth={2.5} strokeDasharray="7 4"
            style={{ opacity: inView ? 1 : 0, transition: "opacity 600ms 1300ms" }} />

          {Array.from({ length: 10 }, (_, i) => i + 1).map((d) => (
            <g key={d}>
              <text x={pad.l - 8} y={cy(d) + cell / 2 + 4} textAnchor="end" fontSize={10.5}
                fill={hover?.o === d ? "var(--terracotta)" : "var(--ink-faint)"} className="num">{d}</text>
              <text x={cx(d) + cell / 2} y={pad.t + side + 16} textAnchor="middle" fontSize={10.5}
                fill={hover?.v === d ? "var(--terracotta)" : "var(--ink-faint)"} className="num">{d}</text>
            </g>
          ))}
          <text x={pad.l + side / 2} y={h - 4} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">
            Volume decile (how the industry ranks) →
          </text>
          <text transform={`translate(12 ${pad.t + side / 2}) rotate(-90)`} textAnchor="middle" fontSize={11}
            fill="var(--ink-mute)">Opportunity decile (this model) →</text>
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <Callout color="var(--terracotta)" value={pct(skipped / total)} label={`of ${METRIC_LABEL[metric].toLowerCase()} the volume rule skips`} />
        <Callout color="var(--plum)" value={pct(over / total)} label={`of ${METRIC_LABEL[metric].toLowerCase()} it over-serves`} />
      </div>
    </div>
  );
}

function Callout({ color, value, label }: { color: string; value: string; label: string }) {
  return (
    <div className="rounded-xl border-l-4 px-3 py-2" style={{ borderColor: color, background: "var(--rule-soft)" }}>
      <div className="num text-[22px] font-semibold" style={{ color }}>{value}</div>
      <div className="text-micro text-ink-mute normal-case tracking-normal">{label}</div>
    </div>
  );
}
