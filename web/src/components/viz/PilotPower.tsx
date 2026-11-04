/**
 * Pilot designer: can the test we are recommending actually find the answer?
 *
 * Inputs come from src/models/decision.py: the break-even effect per listed
 * prescriber, the real year-on-year noise of the prescribers the pilot would
 * run on, the prior-year correlation (for a CUPED adjustment) and the
 * within-territory correlation (for a territory-randomised design). Power is
 * recomputed exactly in the browser as the reader drags.
 */

import { useMemo, useRef, useState } from "react";

import { fmt, mult, pct } from "@/lib/format";
import { useInView } from "@/lib/motion";
import type { PilotDesign, PilotEndpoint } from "@/lib/types";
import { Ring, Slider, Toggle, Tooltip, TipRow, normCdf, smoothPath, svgPoint, useWidth, type Tip } from "./core";

type Endpoint = "share" | "fills";
type Design = "holdout" | "territory";

interface Settings {
  design: Design;
  holdout: number;
  territories: number;
  cuped: boolean;
  effectX: number;
}

function powerAt(ep: PilotEndpoint, p: PilotDesign, s: Settings, months: number, effectX = s.effectX) {
  const t = months / 12;
  const d = ep.effect_per_year * effectX * t;
  const adj = s.cuped ? Math.sqrt(Math.max(1 - ep.prior_rho ** 2, 0)) : 1;
  const sd = ep.sd_per_year * Math.sqrt(t) * adj;
  const N = p.n_list ?? 8878;
  const m = p.prescribers_per_territory ?? 148;
  let se: number;
  if (s.design === "holdout") {
    se = sd * Math.sqrt(1 / (N * (1 - s.holdout)) + 1 / (N * s.holdout));
  } else {
    const n = s.territories * m;
    const deff = 1 + (m - 1) * ep.icc_territory;
    se = sd * Math.sqrt((2 * deff) / n);
  }
  return normCdf(d / se - 1.959964);
}

export function PilotPower({ pilot }: { pilot: PilotDesign }) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [ref, inView] = useInView<SVGSVGElement>(0.25);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const [endpoint, setEndpoint] = useState<Endpoint>("share");
  const [months, setMonths] = useState(6);
  const [s, setS] = useState<Settings>({ design: "holdout", holdout: 0.2, territories: 15, cuped: true, effectX: 1 });

  const ep = pilot[endpoint];
  const other = pilot[endpoint === "share" ? "fills" : "share"];
  const MONTHS = useMemo(() => Array.from({ length: 24 }, (_, i) => i + 1), []);

  if (!ep || !other) return null;

  const power = powerAt(ep, pilot, s, months);
  // Minimum detectable effect, in multiples of break-even, at 80% power.
  let mde = 0;
  for (let k = 0.1; k <= 20; k += 0.05) {
    if (powerAt(ep, pilot, s, months, k) >= 0.8) { mde = k; break; }
  }

  const h = Math.min(360, Math.max(280, width * 0.5));
  const pad = { l: 50, r: 20, t: 20, b: 46 };
  const x = (mo: number) => pad.l + ((mo - 1) / 23) * (width - pad.l - pad.r);
  const y = (p: number) => h - pad.b - p * (h - pad.t - pad.b);
  const curve = smoothPath(MONTHS.map((mo) => [x(mo), y(powerAt(ep, pilot, s, mo))]));
  const ghost = smoothPath(MONTHS.map((mo) => [x(mo), y(powerAt(other, pilot, s, mo))]));

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const p = svgPoint(e, svgRef.current);
    const mo = Math.round(1 + ((p.x - pad.l) / (width - pad.l - pad.r)) * 23);
    if (mo < 1 || mo > 24) { setTip(null); return; }
    setTip({
      x: x(mo), y: y(powerAt(ep, pilot, s, mo)),
      content: (
        <>
          <div className="mb-1 font-semibold">{mo} months</div>
          <TipRow label={`Power, ${endpoint === "share" ? "share pts" : "fills"}`}
            value={pct(powerAt(ep, pilot, s, mo), 0)} color="var(--terracotta-ink)" />
          <TipRow label={`Power, ${endpoint === "share" ? "fills" : "share pts"}`}
            value={pct(powerAt(other, pilot, s, mo), 0)} color="var(--mauve)" />
        </>
      ),
    });
  };

  const verdict = power >= 0.8
    ? "Can detect the break-even response"
    : power >= 0.5 ? "Coin-flip: likely to come back inconclusive" : "Cannot detect it — redesign";

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
      <div>
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <Toggle label="Primary endpoint" value={endpoint} onChange={setEndpoint}
            options={[{ value: "share", label: "Endpoint: share points" }, { value: "fills", label: "Endpoint: branded fills" }]} />
          <Toggle label="Design" value={s.design} onChange={(v) => setS({ ...s, design: v })}
            options={[{ value: "holdout", label: "Prescriber hold-out" }, { value: "territory", label: "Territory split" }]} />
        </div>
        <div ref={wrap} className="relative">
          <svg
            ref={(el) => { svgRef.current = el; ref.current = el; }}
            viewBox={`0 0 ${width} ${h}`} width="100%" height={h}
            className={inView ? "in" : ""}
            onPointerMove={onMove} onPointerLeave={() => setTip(null)}
            role="img" aria-label="Statistical power of the pilot against its duration, for the chosen endpoint and design."
          >
            <rect x={pad.l} y={y(1)} width={width - pad.l - pad.r} height={y(0.8) - y(1)}
              fill="var(--pos)" opacity={0.08} />
            {[0, 0.25, 0.5, 0.8, 1].map((t) => (
              <g key={t}>
                <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)}
                  stroke={t === 0.8 ? "var(--pos)" : "var(--rule)"}
                  strokeDasharray={t === 0.8 ? "6 4" : "2 5"} strokeWidth={t === 0.8 ? 1.5 : 1} />
                <text x={pad.l - 10} y={y(t) + 4} textAnchor="end" fontSize={11}
                  fill={t === 0.8 ? "var(--pos)" : "var(--ink-faint)"} className="num">{pct(t, 0)}</text>
              </g>
            ))}
            <text x={width - pad.r} y={y(0.8) - 7} textAnchor="end" fontSize={11} fill="var(--pos)" fontWeight={600}>
              80% power: the conventional bar
            </text>

            <path d={ghost} fill="none" stroke="var(--mauve)" strokeWidth={2} strokeDasharray="5 4"
              style={{ transition: "d 400ms" }} />
            <path d={curve} pathLength={1} className="draw-path" fill="none" stroke="var(--terracotta)"
              strokeWidth={3.2} style={{ transition: "d 400ms, stroke-dashoffset 1600ms cubic-bezier(.65,0,.35,1)" }} />

            <line x1={x(months)} x2={x(months)} y1={pad.t} y2={h - pad.b} stroke="var(--plum)" strokeOpacity={0.35} />
            <circle cx={x(months)} cy={y(power)} r={8} fill="var(--terracotta)" stroke="var(--panel)" strokeWidth={3}
              style={{ transition: "cx 300ms, cy 300ms" }} />

            {[1, 6, 12, 18, 24].map((t) => (
              <text key={t} x={x(t)} y={h - pad.b + 20} textAnchor="middle" fontSize={11} fill="var(--ink-faint)" className="num">{t}</text>
            ))}
            <text x={(pad.l + width - pad.r) / 2} y={h - 8} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">
              Pilot duration (months) →
            </text>
            <g transform={`translate(${width - pad.r - 190} ${h - pad.b - 44})`} fontSize={11}>
              <line x2={22} y1={6} y2={6} stroke="var(--terracotta)" strokeWidth={3} />
              <text x={28} y={10} fill="var(--ink)">{endpoint === "share" ? "share-point endpoint" : "branded-fill endpoint"}</text>
              <line x2={22} y1={24} y2={24} stroke="var(--mauve)" strokeWidth={2} strokeDasharray="4 3" />
              <text x={28} y={28} fill="var(--ink-mute)">{endpoint === "share" ? "branded-fill endpoint" : "share-point endpoint"}</text>
            </g>
          </svg>
          <Tooltip tip={tip} width={width} />
        </div>
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-4">
          <Ring value={power} label="power" threshold={0.8}
            color={power >= 0.8 ? "var(--pos)" : power >= 0.5 ? "var(--warn)" : "var(--neg)"} />
          <div>
            <div className="text-small font-semibold">{verdict}</div>
            <div className="mt-1 text-micro text-ink-mute normal-case tracking-normal">
              Smallest effect found 80% of the time:{" "}
              <span className="num font-semibold text-ink">{mde ? mult(mde, 1) : "> 20×"}</span> the
              break-even response.
            </div>
          </div>
        </div>
        <Slider label="Duration" value={months} min={1} max={24} step={1} onChange={setMonths}
          display={`${months} months`} marks={[{ at: 6, label: "2 qtrs" }, { at: 12, label: "1 yr" }]} />
        {s.design === "holdout" ? (
          <Slider label="Share of list held out (no calls)" value={s.holdout} min={0.05} max={0.5} step={0.01}
            onChange={(v) => setS({ ...s, holdout: v })} display={`${pct(s.holdout, 0)} · ${fmt((pilot.n_list ?? 0) * s.holdout)} HCPs`} />
        ) : (
          <Slider label="Territories per arm" value={s.territories} min={3} max={Math.floor((pilot.n_territories ?? 60) / 2)}
            step={1} onChange={(v) => setS({ ...s, territories: v })} display={`${s.territories} v ${s.territories}`} />
        )}
        <Slider label="True effect, × break-even" value={s.effectX} min={0.25} max={4} step={0.05}
          onChange={(v) => setS({ ...s, effectX: v })} display={mult(s.effectX, 2)}
          marks={[{ at: 1, label: "break-even" }]} />
        <label className="flex items-center gap-2 text-small">
          <input type="checkbox" checked={s.cuped} onChange={(e) => setS({ ...s, cuped: e.target.checked })}
            className="h-4 w-4 accent-[var(--terracotta)]" />
          Adjust for prior-year trend (CUPED, ρ = {ep.prior_rho.toFixed(2)})
        </label>
        <p className="text-micro text-ink-faint normal-case tracking-normal leading-relaxed">
          Noise is the real 2023→24 change across the {fmt(pilot.n_list)} listed prescribers,
          winsorised at 1/99%. Territory ICC {ep.icc_territory.toFixed(3)}, {fmt(pilot.prescribers_per_territory, 0)} listed
          prescribers per territory. Assumes noise grows with √time.
        </p>
      </div>
    </div>
  );
}
