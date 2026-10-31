/**
 * Headcount explorer: "what would have to be true" for each force size.
 *
 * Public data cannot measure the call response, so the page does not pretend
 * to. It hands the reader the dial instead. Marginal ROI is exactly linear in
 * the response ceiling and in revenue per fill, so for any assumed response
 *
 *     mROI(n) = (ceiling / ceiling_required(n)) * (revenue / revenue_base)
 *
 * where ceiling_required(n) is the pipeline's bisection result for each force
 * size. Nothing is approximated in the browser; the curve is the model's own.
 */

import { useMemo, useRef, useState } from "react";

import { fmt, mult, pct, usd } from "@/lib/format";
import { useInView, useTween } from "@/lib/motion";
import type { DecisionResponse } from "@/lib/types";
import { Slider, Tooltip, TipRow, smoothPath, svgPoint, useWidth, last, type Tip } from "./core";

const LOG_MIN = Math.log10(0.0005);
const LOG_MAX = Math.log10(0.3);

export function HeadcountExplorer({ data }: { data: DecisionResponse }) {
  const [wrap, width] = useWidth<HTMLDivElement>();
  const [ref, inView] = useInView<SVGSVGElement>(0.25);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);

  const current = data.headline.current_n_reps ?? 60;
  const cReq60 = data.headline.required_ceiling_at_current ?? 0.0172;
  const revBase = data.economics.net_revenue_per_30day_fill.base;
  const ira = data.economics.ira_2026_price_per_fill;

  const [logC, setLogC] = useState(Math.log10(cReq60));
  const [rev, setRev] = useState(revBase);
  const c = 10 ** logC;

  const grid = useMemo(
    () => data.required_response.filter((r) => r.required_ceiling && r.required_ceiling > 0)
      .map((r) => ({ n: r.n_reps, req: r.required_ceiling! })),
    [data.required_response],
  );

  const scale = (c * rev) / revBase;
  const mroi = (req: number) => scale / req;

  // Break-even headcount: first n where mROI crosses below 1.
  let breakEven: number | null = null;
  for (let i = 1; i < grid.length; i++) {
    const a = grid[i - 1]!;
    const b = grid[i]!;
    if (mroi(a.req) >= 1 && mroi(b.req) < 1) {
      const f = (mroi(a.req) - 1) / (mroi(a.req) - mroi(b.req));
      breakEven = a.n + f * (b.n - a.n);
      break;
    }
  }
  const allAbove = grid.length > 0 && mroi(last(grid)!.req) >= 1;
  const allBelow = grid.length > 0 && mroi(grid[0]!.req) < 1;
  const at60 = mroi(cReq60);
  const retarget = Number(data.retargeting.hybrid_vs_volume_contribution ?? 0)
    * (c / Number(data.retargeting.priced_ceiling || cReq60)) * (rev / revBase);

  const tweenBE = useTween(breakEven ?? (allAbove ? last(grid)?.n ?? 0 : grid[0]?.n ?? 0), 500);
  const tweenRet = useTween(retarget, 500);

  if (grid.length === 0) return null;

  const h = Math.min(400, Math.max(300, width * 0.55));
  const pad = { l: 54, r: 20, t: 22, b: 46 };
  const nMin = grid[0]!.n;
  const nMax = last(grid)!.n;
  const x = (n: number) => pad.l + ((n - nMin) / (nMax - nMin)) * (width - pad.l - pad.r);
  const Y0 = Math.log10(0.02);
  const Y1 = Math.log10(50);
  const y = (v: number) => {
    const lv = Math.log10(Math.min(Math.max(v, 0.02), 50));
    return h - pad.b - ((lv - Y0) / (Y1 - Y0)) * (h - pad.t - pad.b);
  };
  const pts: [number, number][] = grid.map((g) => [x(g.n), y(mroi(g.req))]);
  const path = smoothPath(pts);
  const area = `${path} L${x(nMax)} ${h - pad.b} L${x(nMin)} ${h - pad.b} Z`;

  const verdict = allBelow
    ? { text: "Shrink the force", tone: "var(--neg)" }
    : at60 >= 1.15 && (breakEven ?? nMax) > current * 1.1
      ? { text: "Add reps", tone: "var(--pos)" }
      : at60 < 0.9
        ? { text: "Shrink the force", tone: "var(--neg)" }
        : { text: "Hold at today's size", tone: "var(--warn)" };

  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const p = svgPoint(e, svgRef.current);
    const n = nMin + ((p.x - pad.l) / (width - pad.l - pad.r)) * (nMax - nMin);
    const g = grid.reduce((a, b) => (Math.abs(b.n - n) < Math.abs(a.n - n) ? b : a));
    setTip({
      x: x(g.n), y: y(mroi(g.req)),
      content: (
        <>
          <div className="mb-1 font-semibold">{g.n} reps</div>
          <TipRow label="Marginal ROI" value={`$${mroi(g.req).toFixed(2)} per $1`} />
          <TipRow label="Response needed" value={pct(g.req * revBase / rev, 2)} />
        </>
      ),
    });
  };

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_280px]">
      <div ref={wrap} className="relative">
        <svg
          ref={(el) => { svgRef.current = el; ref.current = el; }}
          viewBox={`0 0 ${width} ${h}`} width="100%" height={h}
          className={inView ? "in" : ""}
          onPointerMove={onMove} onPointerLeave={() => setTip(null)}
          role="img" aria-label="Marginal return of the last rep against field force size, under the response and price chosen on the sliders."
        >
          <defs>
            <linearGradient id="roiFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0" stopColor="var(--terracotta)" stopOpacity=".32" />
              <stop offset="1" stopColor="var(--terracotta)" stopOpacity="0" />
            </linearGradient>
            <clipPath id="aboveOne">
              <rect x={0} y={0} width={width} height={y(1)} />
            </clipPath>
          </defs>

          {[0.1, 1, 10].map((t) => (
            <g key={t}>
              <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="var(--rule)" strokeDasharray="2 5" />
              <text x={pad.l - 10} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--ink-faint)" className="num">
                ${t}
              </text>
            </g>
          ))}
          <text transform={`translate(14 ${(pad.t + h - pad.b) / 2}) rotate(-90)`} textAnchor="middle"
            fontSize={11} fill="var(--ink-mute)">Return on the last rep, per $1 (log)</text>

          <path d={area} fill="url(#roiFill)" clipPath="url(#aboveOne)" style={{ transition: "d 450ms" }} />
          <line x1={pad.l} x2={width - pad.r} y1={y(1)} y2={y(1)} stroke="var(--neg)" strokeWidth={1.5} strokeDasharray="6 4" />
          <text x={width - pad.r} y={y(1) - 7} textAnchor="end" fontSize={11} fill="var(--neg)" fontWeight={600}>
            break-even: the last rep pays for itself
          </text>

          <path d={path} pathLength={1} className="draw-path" fill="none" stroke="var(--terracotta)"
            strokeWidth={3} style={{ transition: "d 450ms, stroke-dashoffset 1600ms cubic-bezier(.65,0,.35,1)" }} />

          {/* today */}
          <line x1={x(current)} x2={x(current)} y1={pad.t} y2={h - pad.b} stroke="var(--plum)" strokeOpacity=".5" />
          <circle cx={x(current)} cy={y(at60)} r={7} fill="var(--plum)" stroke="var(--panel)" strokeWidth={3}
            style={{ transition: "cy 450ms" }} />
          <text x={x(current) + 8} y={pad.t + 10} fontSize={11} fill="var(--ink)" fontWeight={600}>today · {current}</text>

          {breakEven != null && (
            <g>
              <circle cx={x(tweenBE)} cy={y(1)} r={10} fill="var(--terracotta)" opacity={0.45} className="pulse-ring" />
              <circle cx={x(tweenBE)} cy={y(1)} r={6} fill="var(--terracotta)" stroke="var(--panel)" strokeWidth={2} />
              <text x={x(tweenBE)} y={y(1) + 22} textAnchor="middle" fontSize={11} fill="var(--terracotta)" fontWeight={700} className="num">
                {fmt(tweenBE, 0)} reps
              </text>
            </g>
          )}

          {[nMin, Math.round((nMin + nMax) / 2), nMax].map((t) => (
            <text key={t} x={x(t)} y={h - pad.b + 20} textAnchor="middle" fontSize={11} fill="var(--ink-faint)" className="num">{t}</text>
          ))}
          <text x={(pad.l + width - pad.r) / 2} y={h - 8} textAnchor="middle" fontSize={11} fill="var(--ink-mute)">
            Field force size (reps) →
          </text>
        </svg>
        <Tooltip tip={tip} width={width} />
      </div>

      <div className="flex flex-col gap-5">
        <Slider
          label="Assumed call response"
          value={logC} min={LOG_MIN} max={LOG_MAX} step={0.01}
          onChange={setLogC}
          display={`${pct(c, c < 0.01 ? 2 : 1)} of headroom / yr`}
          marks={[
            { at: Math.log10(cReq60), label: "break-even" },
            { at: Math.log10(0.28), label: "old config" },
          ]}
        />
        <Slider
          label="Net revenue per 30-day fill"
          value={rev} min={180} max={460} step={1}
          onChange={setRev}
          display={usd(rev)}
          marks={[{ at: ira, label: "IRA 2026" }, { at: revBase, label: "base" }]}
        />
        <div className="rounded-xl p-4" style={{ background: "color-mix(in oklab, var(--terracotta) 9%, transparent)" }}>
          <div className="eyebrow">Verdict under these inputs</div>
          <div className="display mt-1 text-[26px]" style={{ color: verdict.tone }}>{verdict.text}</div>
          <dl className="mt-3 space-y-1 text-small">
            <Row k={`Last rep at ${current}`} v={`$${at60.toFixed(2)} per $1`} />
            <Row k="Break-even force" v={breakEven != null ? `${fmt(breakEven, 0)} reps`
              : allAbove ? `> ${nMax} reps` : `< ${nMin} reps`} />
            <Row k="Value of re-targeting" v={`${usd(tweenRet)} / yr`} />
            <Row k="Response vs break-even" v={mult(c / cReq60, 2)} />
          </dl>
        </div>
        <p className="text-micro text-ink-faint normal-case tracking-normal leading-relaxed">
          The measured response from public data is <strong>zero / not identified</strong>, so
          no setting here is a forecast. The IRA mark is CMS&apos;s published 2026 Medicare
          negotiated price for a 30-day supply: from 2026 every Part D call is worth less,
          and the break-even response rises to {pct(cReq60 * revBase / ira, 2)}.
        </p>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-ink-mute">{k}</dt>
      <dd className="num font-semibold">{v}</dd>
    </div>
  );
}
