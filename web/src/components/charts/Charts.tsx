/**
 * Hand-rolled SVG charts.
 *
 * No charting library. Every one of them ships an opinionated theme that has to
 * be fought, and the fight costs more than drawing the marks. These are small
 * because charts should be: a title stating the finding, the marks, one
 * annotation, a source line. Everything else is chart junk.
 *
 * Universal rules applied here:
 *   - action titles live in the calling component, not the chart
 *   - the point being made is ANNOTATED, never left for the reader to find
 *   - no gridlines unless reading an exact value matters
 *   - direct labelling instead of legends wherever it fits
 */

import { fmt, pct, stat } from "@/lib/format";
import { heatAlpha, linear, niceMax } from "@/lib/scales";
import type { DisagreementCell, LiftRow, ReachPoint, RoiPoint, TornadoRow } from "@/lib/types";

const AXIS = "var(--ink-faint)";
const RULE = "var(--rule)";

/* ============================================================ disagreement */

/**
 * Exhibit E1. Rows = opportunity decile, columns = volume decile.
 * Both axes labelled explicitly -- this is the one chart where confusing the
 * two would invert the entire argument.
 */
export function DisagreementMatrix({ cells, onHover }: {
  cells: DisagreementCell[];
  onHover?: (c: DisagreementCell | null) => void;
}) {
  if (cells.length === 0) return null;
  const max = Math.max(...cells.map((c) => c.hcp_count), 1);
  const lookup = new Map(cells.map((c) => [`${c.opportunity_decile}:${c.volume_decile}`, c]));

  const rows = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1];
  const cols = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

  return (
    <div className="overflow-x-auto">
      <table className="border-collapse" style={{ borderSpacing: 0 }}>
        <tbody>
          {rows.map((o) => (
            <tr key={o}>
              <th
                scope="row"
                className="num pr-1.5 text-right text-micro font-normal"
                style={{ color: AXIS }}
              >
                {o}
              </th>
              {cols.map((v) => {
                const c = lookup.get(`${o}:${v}`);
                const n = c?.hcp_count ?? 0;
                // The two regions that carry the argument: prescribers the
                // volume rule skips, and prescribers it over-serves.
                const skipped = o >= 7 && v <= 4;
                const overserved = o <= 4 && v >= 7;
                return (
                  <td
                    key={v}
                    onMouseEnter={() => onHover?.(c ?? null)}
                    onMouseLeave={() => onHover?.(null)}
                    title={`Volume ${v} / opportunity ${o}: ${fmt(n)} prescribers`}
                    style={{
                      width: 30, height: 26,
                      background: heatAlpha(n, max),
                      border: "1px solid var(--panel)",
                      outline: skipped
                        ? "2px solid var(--pos)"
                        : overserved
                          ? "2px solid var(--neg)"
                          : undefined,
                      outlineOffset: -2,
                    }}
                  />
                );
              })}
            </tr>
          ))}
          <tr>
            <th />
            {cols.map((v) => (
              <th
                key={v}
                className="num pt-1 text-center text-micro font-normal"
                style={{ color: AXIS }}
              >
                {v}
              </th>
            ))}
          </tr>
        </tbody>
      </table>
      <p className="text-micro text-ink-faint mt-2 normal-case tracking-normal leading-relaxed">
        <strong className="text-ink-mute">Rows</strong> opportunity decile ·{" "}
        <strong className="text-ink-mute">columns</strong> volume decile. Off-diagonal
        mass is the finding.
        <br />
        <span style={{ color: "var(--pos)" }}>▢</span> low volume / high opportunity — the
        volume rule skips these.{" "}
        <span style={{ color: "var(--neg)" }}>▢</span> high volume / low opportunity — the
        volume rule over-serves these.
      </p>
    </div>
  );
}

/* ================================================================== reach */

/** Exhibit E3. Three allocation rules against one budget. Directly labelled. */
export function ReachCurve({ points, w = 520, h = 220 }: {
  points: ReachPoint[];
  w?: number;
  h?: number;
}) {
  if (points.length === 0) return null;
  const pad = { l: 44, r: 78, t: 12, b: 34 };
  const x = linear([0, 1], [pad.l, w - pad.r]);
  const y = linear([0, 1], [h - pad.b, pad.t]);

  const series: { rule: ReachPoint["rule"]; color: string; label: string; dash?: string }[] = [
    { rule: "opportunity", color: "var(--d10)", label: "Opportunity" },
    { rule: "volume", color: "var(--v8)", label: "Volume" },
    { rule: "geography", color: "var(--ink-faint)", label: "Geography", dash: "4 3" },
  ];

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img"
      aria-label="Share of addressable opportunity reached, by targeting rule, against share of the prescriber universe called.">
      <line x1={pad.l} x2={w - pad.r} y1={h - pad.b} y2={h - pad.b} stroke={RULE} />
      <line x1={pad.l} x2={pad.l} y1={pad.t} y2={h - pad.b} stroke={RULE} />

      {series.map((s) => {
        const pts = points
          .filter((p) => p.rule === s.rule)
          .sort((a, b) => a.pct_of_universe - b.pct_of_universe);
        if (pts.length === 0) return null;
        const d = pts
          .map((p, i) => `${i ? "L" : "M"}${x(p.pct_of_universe).toFixed(1)} ${y(p.pct_opportunity_reached).toFixed(1)}`)
          .join(" ");
        const last = pts[pts.length - 1]!;
        return (
          <g key={s.rule}>
            <path d={d} fill="none" stroke={s.color} strokeWidth={1.8} strokeDasharray={s.dash} />
            {/* Direct labelling beats a legend: no lookup, no colour matching. */}
            <text
              x={w - pad.r + 6}
              y={y(last.pct_opportunity_reached) + 3}
              fontSize={10}
              fill={s.color}
            >
              {s.label}
            </text>
          </g>
        );
      })}

      {[0, 0.5, 1].map((t) => (
        <text key={t} x={pad.l - 6} y={y(t) + 3} textAnchor="end" fontSize={9}
          fill={AXIS} className="num">{pct(t, 0)}</text>
      ))}
      {[0, 0.5, 1].map((t) => (
        <text key={t} x={x(t)} y={h - pad.b + 14} textAnchor="middle" fontSize={9}
          fill={AXIS} className="num">{pct(t, 0)}</text>
      ))}
      <text x={(pad.l + w - pad.r) / 2} y={h - 3} textAnchor="middle" fontSize={10} fill={AXIS}>
        Share of prescriber universe called
      </text>
    </svg>
  );
}

/* ==================================================================== ROI */

/** Exhibit E4. Break-even is DRAWN and LABELLED, never left to be inferred. */
export function RoiCurve({ points, currentReps, w = 520, h = 220 }: {
  points: RoiPoint[];
  currentReps?: number | null;
  w?: number;
  h?: number;
}) {
  const pts = points.filter((p) => p.marginal_roi !== null && Number.isFinite(p.marginal_roi));
  if (pts.length === 0) return null;

  const pad = { l: 46, r: 16, t: 14, b: 34 };
  const xs = pts.map((p) => p.n_reps);
  const ys = pts.map((p) => p.marginal_roi!);
  const yMax = niceMax(Math.max(...ys, 1.2));
  const x = linear([Math.min(...xs), Math.max(...xs)], [pad.l, w - pad.r]);
  const y = linear([0, yMax], [h - pad.b, pad.t]);

  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(p.n_reps).toFixed(1)} ${y(p.marginal_roi!).toFixed(1)}`).join(" ");

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img"
      aria-label="Marginal return per additional sales representative, against field force size, with the break-even line marked.">
      <line x1={pad.l} x2={w - pad.r} y1={h - pad.b} y2={h - pad.b} stroke={RULE} />
      <line x1={pad.l} x2={pad.l} y1={pad.t} y2={h - pad.b} stroke={RULE} />

      {/* The break-even rule. This annotation IS the finding. */}
      <line x1={pad.l} x2={w - pad.r} y1={y(1)} y2={y(1)}
        stroke="var(--neg)" strokeDasharray="3 3" strokeWidth={1} />
      <text x={w - pad.r} y={y(1) - 5} textAnchor="end" fontSize={9}
        fill="var(--neg)" className="num">break-even</text>

      <path d={d} fill="none" stroke="var(--a5-core, #B8862B)" strokeWidth={2} />

      {currentReps != null && (
        <>
          <line x1={x(currentReps)} x2={x(currentReps)} y1={pad.t} y2={h - pad.b}
            stroke="var(--ink-faint)" strokeDasharray="2 3" strokeWidth={1} />
          <text x={x(currentReps) + 4} y={pad.t + 10} fontSize={9} fill={AXIS} className="num">
            today {currentReps}
          </text>
        </>
      )}

      {[0, 1, yMax].map((t) => (
        <text key={t} x={pad.l - 6} y={y(t) + 3} textAnchor="end" fontSize={9}
          fill={AXIS} className="num">{stat(t, 1)}</text>
      ))}
      <text x={x(Math.min(...xs))} y={h - pad.b + 14} fontSize={9} fill={AXIS} className="num">
        {Math.min(...xs)}
      </text>
      <text x={x(Math.max(...xs))} y={h - pad.b + 14} textAnchor="end" fontSize={9}
        fill={AXIS} className="num">{Math.max(...xs)}</text>
      <text x={(pad.l + w - pad.r) / 2} y={h - 3} textAnchor="middle" fontSize={10} fill={AXIS}>
        Field force size (reps)
      </text>
    </svg>
  );
}

/* =================================================================== lift */

/** Exhibit E2. Grouped bars: chromatic opportunity vs neutral volume. */
export function LiftChart({ rows, w = 520, h = 220 }: {
  rows: LiftRow[];
  w?: number;
  h?: number;
}) {
  if (rows.length === 0) return null;
  const pad = { l: 46, r: 14, t: 14, b: 34 };
  const deciles = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const maxY = niceMax(Math.max(...rows.map((r) => r.mean_growth_abs), 1));
  const y = linear([0, maxY], [h - pad.b, pad.t]);
  const bandW = (w - pad.l - pad.r) / deciles.length;

  const get = (rule: LiftRow["rule"], d: number) =>
    rows.find((r) => r.rule === rule && r.decile === d)?.mean_growth_abs ?? 0;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" role="img"
      aria-label="Mean realised growth in the held-out year, by predicted decile, for the opportunity rule versus the volume rule.">
      <line x1={pad.l} x2={w - pad.r} y1={h - pad.b} y2={h - pad.b} stroke={RULE} />
      <line x1={pad.l} x2={pad.l} y1={pad.t} y2={h - pad.b} stroke={RULE} />

      {deciles.map((d, i) => {
        const x0 = pad.l + i * bandW;
        const o = get("opportunity", d);
        const v = get("volume", d);
        const bw = bandW * 0.36;
        return (
          <g key={d}>
            <rect x={x0 + bandW * 0.1} y={y(o)} width={bw} height={h - pad.b - y(o)}
              fill="var(--d9)" />
            <rect x={x0 + bandW * 0.52} y={y(v)} width={bw} height={h - pad.b - y(v)}
              fill="var(--v6)" />
            <text x={x0 + bandW / 2} y={h - pad.b + 13} textAnchor="middle" fontSize={9}
              fill={AXIS} className="num">{d}</text>
          </g>
        );
      })}

      <g transform={`translate(${pad.l + 8},${pad.t + 4})`}>
        <rect width={9} height={9} fill="var(--d9)" />
        <text x={13} y={8} fontSize={9} fill={AXIS}>Opportunity</text>
        <rect y={13} width={9} height={9} fill="var(--v6)" />
        <text x={13} y={21} fontSize={9} fill={AXIS}>Volume</text>
      </g>

      <text x={(pad.l + w - pad.r) / 2} y={h - 3} textAnchor="middle" fontSize={10} fill={AXIS}>
        Predicted decile
      </text>
    </svg>
  );
}

/* ================================================================ tornado */

/** Which assumption should you argue with first? Sorted by absolute swing. */
export function Tornado({ rows, w = 520 }: { rows: TornadoRow[]; w?: number }) {
  if (rows.length === 0) return null;
  const maxSwing = Math.max(...rows.map((r) => r.swing), 1);
  return (
    <div className="flex flex-col gap-1.5" style={{ maxWidth: w }}>
      {rows.map((r) => {
        const lo = Math.min(r.break_even_low, r.break_even_high);
        const hi = Math.max(r.break_even_low, r.break_even_high);
        const width = (r.swing / maxSwing) * 100;
        return (
          <div key={r.assumption} className="flex items-center gap-2" title={r.basis}>
            <span className="w-[168px] shrink-0 truncate text-micro text-ink-mute normal-case tracking-normal">
              {r.assumption.replace(/_/g, " ")}
            </span>
            <span className="relative h-2.5 flex-1 rounded-sm" style={{ background: "var(--rule-soft)" }}>
              <span className="absolute inset-y-0 rounded-sm"
                style={{ left: 0, width: `${width}%`, background: "var(--a5-core, #B8862B)" }} />
            </span>
            <span className="num w-[92px] shrink-0 text-right text-micro">
              {fmt(lo, 0)}–{fmt(hi, 0)}
            </span>
          </div>
        );
      })}
      <p className="text-micro text-ink-faint mt-1 normal-case tracking-normal">
        Break-even headcount across each assumption&apos;s stated range, everything else
        held at base. The longest bar is the assumption worth arguing about.
      </p>
    </div>
  );
}
