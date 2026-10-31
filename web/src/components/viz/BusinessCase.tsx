/**
 * The business case under uncertainty.
 *
 *   BeliefExplorer  expected two-year value of cut / hold / grow / pilot-then-
 *                   decide as the reader's belief about the call response moves.
 *                   The band where the pilot wins is shaded: that is the answer
 *                   to "is the pilot worth it?" for every belief at once.
 *   PayoffMatrix    each decision under each true response, with regret, so
 *                   the robust choice (lowest worst-case regret) is visible.
 *
 * Recomputed in the browser by lib/decisionMath.ts from the pipeline's K(n)
 * grid; the pipeline's 20,000-draw numbers (src/models/value.py) are the
 * reference values quoted in the deck.
 */

import { useMemo, useRef, useState } from "react";

import { usd } from "@/lib/format";
import { useInView } from "@/lib/motion";
import { Economy, strategyValues, type Params, type StrategyValues } from "@/lib/decisionMath";
import type { BusinessCaseValue, DecisionResponse, PayoffRow } from "@/lib/types";
import { Slider, Toggle, Tooltip, TipRow, smoothPath, svgPoint, useWidth, type Tip } from "./core";

const SERIES: { key: keyof Pick<StrategyValues, "hold" | "cut" | "grow" | "pilot">; label: string; color: string; w: number; dash?: string }[] = [
  { key: "pilot", label: "Hold + pilot, then decide", color: "var(--terracotta)", w: 3.4 },
  { key: "grow", label: "Grow now (+30 reps)", color: "var(--plum)", w: 2.2 },
  { key: "cut", label: "Cut now (−20 reps)", color: "var(--mauve-ink)", w: 2.2, dash: "6 4" },
  { key: "hold", label: "Hold, no pilot", color: "var(--ink-faint)", w: 1.5, dash: "2 4" },
];

const XS = Array.from({ length: 25 }, (_, i) => 0.25 * Math.pow(16, i / 24));   // 0.25x -> 4x

function params(bc: BusinessCaseValue): Params {
  return {
    current: bc.current_n_reps ?? 60,
    cReq: bc.break_even_ceiling ?? 0.0172,
    seC: bc.pilot_se_ceiling ?? 0.005,
    hire: bc.rep_hire_cost ?? 60_000,
    rampMonths: bc.rep_ramp_months ?? 6,
    separation: bc.rep_separation_cost ?? 50_000,
    holdoutCostFraction: bc.holdout_cost_fraction ?? 0.085,
    pilotMonths: bc.pilot_months ?? 6,
  };
}

export function BeliefExplorer({ data }: { data: DecisionResponse }) {
  const bc = data.business_case;
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [ref, inView] = useInView<SVGSVGElement>(0.25);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const [logX, setLogX] = useState(0);                 // belief median, log2 of x break-even
  const [logSd, setLogSd] = useState(bc.prior_log_sd ?? 1);
  const [horizon, setHorizon] = useState(bc.horizon_years ?? 2);

  const p = useMemo(() => params(bc), [bc]);
  const eco = useMemo(() => (data.value_grid.length ? new Economy(data.value_grid, p) : null), [data.value_grid, p]);
  const curves = useMemo(
    () => (eco ? XS.map((x) => strategyValues(eco, p, x, logSd, horizon, 900, 11)) : []),
    [eco, p, logSd, horizon],
  );
  const medianX = Math.pow(2, logX);
  const here = useMemo(
    () => (eco ? strategyValues(eco, p, medianX, logSd, horizon, 3000, 5) : null),
    [eco, p, medianX, logSd, horizon],
  );

  if (!eco || !here || curves.length === 0) return null;

  const h = Math.min(420, Math.max(320, width * 0.56));
  const pad = { l: 64, r: 20, t: 22, b: 48 };
  const lx = (x: number) => pad.l + ((Math.log(x) - Math.log(0.25)) / (Math.log(4) - Math.log(0.25))) * (width - pad.l - pad.r);
  const all = curves.flatMap((c) => [c.cut, c.grow, c.pilot, 0]);
  const yMin = Math.max(Math.min(...all), -80e6);
  const yMax = Math.min(Math.max(...all), 80e6);
  const y = (v: number) => h - pad.b - ((Math.max(Math.min(v, yMax), yMin) - yMin) / (yMax - yMin || 1)) * (h - pad.t - pad.b);

  // Contiguous band where the pilot is the best strategy.
  const band = XS.filter((_, i) => curves[i]!.best === "pilot");
  const bandLo = band.length ? band[0]! : null;
  const bandHi = band.length ? band[band.length - 1]! : null;

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const pt = svgPoint(e, svgRef.current);
    const i = Math.round(((pt.x - pad.l) / (width - pad.l - pad.r)) * (XS.length - 1));
    if (i < 0 || i >= XS.length) { setTip(null); return; }
    const c = curves[i]!;
    setTip({
      x: lx(XS[i]!), y: pad.t + 40,
      content: (
        <>
          <div className="mb-1 font-semibold">Belief: calls work {XS[i]!.toFixed(2)}× break-even</div>
          {SERIES.map((s) => <TipRow key={s.key} label={s.label} value={usd(c[s.key])} color={s.color} />)}
        </>
      ),
    });
  };

  const ticks = [0.25, 0.5, 1, 2, 4];
  const yTicks = niceTicks(yMin, yMax);

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
      <div ref={wrap} className="relative">
        <svg ref={(el) => { svgRef.current = el; ref.current = el; }} viewBox={`0 0 ${width} ${h}`} width="100%" height={h}
          className={inView ? "in" : ""} onPointerMove={onMove} onPointerLeave={() => setTip(null)}
          role="img" aria-label="Expected two-year value of each headcount strategy against belief about the call response.">
          {bandLo != null && bandHi != null && (
            <g>
              <rect x={lx(bandLo)} y={pad.t} width={Math.max(lx(bandHi) - lx(bandLo), 4)} height={h - pad.t - pad.b}
                fill="var(--terracotta)" opacity={0.09} rx={8} />
              <text x={(lx(bandLo) + lx(bandHi)) / 2} y={pad.t + 14} textAnchor="middle" fontSize={11}
                fill="var(--terracotta)" fontWeight={700}>the pilot wins here</text>
            </g>
          )}
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--ink-faint)" : "var(--rule)"}
                strokeDasharray={t === 0 ? undefined : "2 5"} />
              <text x={pad.l - 10} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--ink-faint)" className="num">{usd(t)}</text>
            </g>
          ))}
          {ticks.map((t) => (
            <text key={t} x={lx(t)} y={h - pad.b + 20} textAnchor="middle" fontSize={11} fill="var(--ink-faint)" className="num">{t}×</text>
          ))}
          <text x={(pad.l + width - pad.r) / 2} y={h - 8} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">
            Your belief: how well calls work, × the break-even response (log) →
          </text>
          <text transform={`translate(14 ${(pad.t + h - pad.b) / 2}) rotate(-90)`} textAnchor="middle" fontSize={11}
            fill="var(--ink-mute)">Expected value vs holding, {horizon} yrs</text>

          {SERIES.map((s, i) => (
            <path key={s.key} d={smoothPath(XS.map((x, j) => [lx(x), y(curves[j]![s.key])]))}
              pathLength={1} className={s.dash ? "" : "draw-path"} fill="none" stroke={s.color} strokeWidth={s.w}
              strokeDasharray={s.dash} style={{ transition: "d 400ms", transitionDelay: `${i * 150}ms` }} />
          ))}

          <line x1={lx(medianX)} x2={lx(medianX)} y1={pad.t} y2={h - pad.b} stroke="var(--plum)" strokeOpacity={0.4} />
          {SERIES.slice(0, 3).map((s) => (
            <circle key={s.key} cx={lx(medianX)} cy={y(here[s.key])} r={s.key === "pilot" ? 7 : 5}
              fill={s.color} stroke="var(--panel)" strokeWidth={2} style={{ transition: "cy 300ms, cx 300ms" }} />
          ))}

          <g transform={`translate(${pad.l + 12} ${pad.t + 34})`} fontSize={11}>
            {SERIES.map((s, i) => (
              <g key={s.key} transform={`translate(0 ${i * 17})`}>
                <line x2={22} y1={0} y2={0} stroke={s.color} strokeWidth={s.w} strokeDasharray={s.dash} />
                <text x={28} y={4} fill="var(--ink)">{s.label}</text>
              </g>
            ))}
          </g>
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>

      <div className="flex flex-col gap-5">
        <Slider label="Your belief about the response" value={logX} min={-2} max={2} step={0.05} onChange={setLogX}
          display={`${medianX.toFixed(2)}× break-even`}
          marks={[{ at: -1, label: "0.5×" }, { at: 0, label: "break-even" }, { at: 1, label: "2×" }]} />
        <Slider label="How unsure you are (log-sd)" value={logSd} min={0.3} max={1.6} step={0.05} onChange={setLogSd}
          display={`× / ÷ ${Math.exp(1.645 * logSd).toFixed(1)} at 90%`} />
        <Slider label="Horizon (to generic entry)" value={horizon} min={1} max={3} step={0.5} onChange={setHorizon}
          display={`${horizon} years`} />
        <div className="rounded-xl p-4" style={{ background: "color-mix(in oklab, var(--terracotta) 9%, transparent)" }}>
          <div className="eyebrow">Best strategy for this belief</div>
          <div className="display mt-1 text-[24px]" style={{ color: here.best === "pilot" ? "var(--terracotta)" : "var(--plum)" }}>
            {SERIES.find((s) => s.key === here.best)?.label}
          </div>
          <dl className="mt-3 space-y-1 text-small">
            {SERIES.map((s) => (
              <div key={s.key} className="flex justify-between gap-3">
                <dt className="text-ink-mute">{s.label}</dt>
                <dd className="num font-semibold">{usd(here[s.key])}</dd>
              </div>
            ))}
            <div className="flex justify-between gap-3 border-t border-rule pt-1">
              <dt className="text-ink-mute">Pilot&apos;s own cost</dt>
              <dd className="num font-semibold">{usd(here.pilotCost)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-ink-mute">Pilot then says grow / cut</dt>
              <dd className="num font-semibold">{(here.pSaysGrow * 100).toFixed(0)}% / {(here.pSaysCut * 100).toFixed(0)}%</dd>
            </div>
          </dl>
        </div>
      </div>
    </div>
  );
}

function niceTicks(lo: number, hi: number): number[] {
  const span = hi - lo;
  const step = span > 60e6 ? 20e6 : span > 30e6 ? 10e6 : span > 12e6 ? 5e6 : 2e6;
  const out: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) out.push(t);
  if (!out.includes(0)) out.push(0);
  return out.sort((a, b) => a - b);
}

/* ---------------------------------------------------------------- matrix */

const DEC_LABEL: Record<PayoffRow["decision"], string> = {
  pilot: "Hold + pilot",
  hold: "Hold, no pilot",
  grow: "Grow now",
  cut: "Cut now",
};

export function PayoffMatrix({ bc }: { bc: BusinessCaseValue }) {
  const [ref, inView] = useInView<HTMLDivElement>(0.3);
  const [mode, setMode] = useState<"value" | "regret">("regret");
  const rows = bc.payoff ?? [];
  if (rows.length === 0) return null;
  const xs = [...new Set(rows.map((r) => r.response_x))].sort((a, b) => a - b);
  const decs: PayoffRow["decision"][] = ["pilot", "hold", "grow", "cut"];
  const get = (d: string, x: number) => rows.find((r) => r.decision === d && r.response_x === x);
  const worst = bc.max_regret ?? {};
  const robust = bc.minimax_regret_decision;
  const maxAbs = Math.max(...rows.map((r) => Math.abs(mode === "value" ? r.value_vs_hold : r.regret)), 1);

  return (
    <div ref={ref}>
      <div className="mb-3">
        <Toggle label="Show" value={mode} onChange={setMode} options={[
          { value: "regret", label: "Regret (what you would wish you had done)" },
          { value: "value", label: "Value vs holding" },
        ]} />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-separate text-small" style={{ borderSpacing: 4 }}>
          <thead>
            <tr>
              <th className="eyebrow text-left">If calls truly work…</th>
              {xs.map((x) => <th key={x} className="eyebrow text-center">{x}× b-e</th>)}
              <th className="eyebrow text-right">Worst regret</th>
            </tr>
          </thead>
          <tbody>
            {decs.map((d, i) => (
              <tr key={d}>
                <td className="py-1 font-semibold" style={{ color: d === robust ? "var(--terracotta)" : undefined }}>
                  {DEC_LABEL[d]} {d === robust && <span className="ml-1 rounded-full px-2 py-0.5 text-[10px] text-white" style={{ background: "var(--terracotta)" }}>robust</span>}
                </td>
                {xs.map((x, j) => {
                  const r = get(d, x);
                  const v = r ? (mode === "value" ? r.value_vs_hold : r.regret) : 0;
                  const a = Math.min(Math.abs(v) / maxAbs, 1);
                  const good = mode === "value" ? v >= 0 : v < 1;
                  const bg = mode === "regret"
                    ? `rgba(163,38,62,${0.06 + a * 0.55})`
                    : v >= 0 ? `rgba(76,125,90,${0.08 + a * 0.6})` : `rgba(163,38,62,${0.08 + a * 0.6})`;
                  return (
                    <td key={x} className="num rounded-lg px-2 py-2 text-center font-medium"
                      style={{
                        background: mode === "regret" && good ? "rgba(76,125,90,.16)" : bg,
                        color: a > 0.6 ? "#fff" : "var(--ink)",
                        opacity: inView ? 1 : 0,
                        transform: inView ? "none" : "scale(.8)",
                        transition: `opacity 500ms ${(i * xs.length + j) * 35}ms, transform 500ms cubic-bezier(.34,1.56,.64,1) ${(i * xs.length + j) * 35}ms`,
                      }}>
                      {usd(v)}
                    </td>
                  );
                })}
                <td className="num px-2 text-right font-semibold" style={{ color: d === robust ? "var(--terracotta)" : undefined }}>
                  {usd(worst[d])}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
