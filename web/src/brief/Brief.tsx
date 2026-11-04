/**
 * Present mode -- the 10-slide steering-committee brief, live.
 *
 * Same storyline as outputs/PharmaTarget_Executive.pdf, but every exhibit is
 * the interactive one, so a question in the room ("what if calls work half as
 * well?") is answered by dragging, not by "we'll come back to you".
 *
 *   ← / →, PgUp / PgDn, space   navigate      F   full screen
 *   Home / End                  first / last  Esc leave
 *
 * The printable version is the PDF deck (Deck PDF in the bar).
 */

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { fmt, mult, pct, usd } from "@/lib/format";
import { BeliefExplorer } from "@/components/viz/BusinessCase";
import { FrontierChart } from "@/components/viz/FrontierChart";
import { HeadcountExplorer } from "@/components/viz/HeadcountExplorer";
import { MatrixViz } from "@/components/viz/MatrixViz";
import { PilotPower } from "@/components/viz/PilotPower";
import { RuleRace, type RaceRow } from "@/components/viz/RuleRace";

interface Slide {
  eyebrow: string;
  kind?: string;
  title: string;
  body?: ReactNode;
  points?: string[];
  soWhat?: string;
  dark?: boolean;
}

export function Brief() {
  const summary = useQuery({ queryKey: qk.summary, queryFn: api.summary });
  const decision = useQuery({ queryKey: qk.decision, queryFn: api.decision });
  const callplan = useQuery({ queryKey: qk.callplan, queryFn: api.callplan });
  const territories = useQuery({ queryKey: qk.territories(60, "optimised"), queryFn: () => api.territories(60, "optimised") });
  const nav = useNavigate();
  const [i, setI] = useState(() => {
    const n = Number(new URLSearchParams(window.location.search).get("s"));
    return Number.isFinite(n) && n >= 1 ? n - 1 : 0;
  });

  const s = summary.data;
  const d = decision.data;
  const rec = s?.headlines.recommendation;
  const terr = s?.territory;
  const dis = s?.disagreement;
  const h1 = s?.headlines.h1;
  const fr = d?.frontier_summary;
  const sh = d?.pilot.share;
  const fl = d?.pilot.fills;
  const bc = d?.business_case;
  const rt = bc?.retargeting_per_year_by_response;
  const race: RaceRow[] = Object.entries(s?.headlines.business_case?.rules ?? {}).map(([rule, o]) => ({ rule, ...o }));

  const slides: Slide[] = [
    { eyebrow: "PharmaTarget · DOAC field strategy", title: "Target the gap, not the volume.", dark: true,
      body: <TitleBody rec={rec?.share_vs_volume} imb={[terr?.imbalance_before, terr?.imbalance_after]} power={sh?.power_holdout20_6m} /> },
    { eyebrow: "Executive summary", title: "Re-target and redraw now; hold headcount and let a two-quarter pilot decide it",
      body: <Summary rows={[
        ["Do now", "var(--pos)", "Re-target the 60-rep list", `50/50 blend: ${mult(rec?.share_vs_volume)} the share gains, ${pct(rec?.abs_vs_volume, 0)} of growth kept, clears the floor in ${pct(fr?.equal_weight_p_clears_floor, 0)} of re-draws.`],
        ["Do now", "var(--pos)", "Redraw the territories", `Imbalance ${mult(terr?.imbalance_before, 0)} → ${mult(terr?.imbalance_after, 1)}, 100% contiguous, travel ${pct(terr?.travel_reduction_pct, 0)} shorter.`],
        ["Test first", "var(--warn)", "Hold 60, run the pilot", `20% hold-out on share points: ${pct(sh?.power_holdout20_6m, 0)} power in six months; lowest worst-case regret.`],
      ]} stack={[
        [`${usd(rt?.["1.0"])}/yr`, "re-targeting, zero cost"],
        [usd(bc?.base_pilot_value), "pilot vs deciding blind"],
        [bc?.grow_pays_above_x != null ? `≥ ${bc.grow_pays_above_x}×` : "–", "belief needed to hire now"],
        ["$0", "new headcount before read-out"],
      ]} /> },
    { eyebrow: "The problem", kind: "ARITHMETIC",
      title: `The two rankings disagree for ${pct(dis?.disagree_by_2plus_pct, 0)} of prescribers`,
      body: callplan.data ? <MatrixViz cells={callplan.data.disagreement_matrix} /> : null,
      points: [`${fmt(dis?.volume_low_opportunity_high)} low-volume, high-opportunity writers are skipped`,
        `${fmt(dis?.volume_high_opportunity_low)} high-volume, low-headroom writers are over-served`,
        "Opportunity = what a strong comparable reaches, minus what this one gives the brand"],
      soWhat: "The list, not the headcount, is the first lever: it is free to change." },
    { eyebrow: "The evidence", kind: "BACK-TESTED",
      title: `In a year the model never saw, flagged prescribers grew ${mult(h1?.matched_growth_ratio)} as fast as matched peers`,
      body: <RuleRace rows={race} />,
      points: [`+${fmt(h1?.matched_paired_difference, 1)} fills per prescriber [${fmt(h1?.matched_ci?.[0], 1)}, ${fmt(h1?.matched_ci?.[1], 1)}]`,
        "Each pure rule wins one metric; the blend is near the top of both",
        "Where growth happened, not what a call caused: that is the pilot's job"],
      soWhat: "The ranking finds growing prescribers out of time; it is not fitted to the exam." },
    { eyebrow: "The decision rule", kind: "BACK-TESTED",
      title: "50/50 wins share without giving up the base; a weight tuned on last year fails this year",
      body: d ? <FrontierChart rows={d.frontier} floor={fr?.abs_floor_vs_volume ?? 0.9} tuned={fr?.selected_weight ?? null} /> : null,
      soWhat: `Adopt 50/50; for 95% confidence of keeping the base use ${pct(fr?.robust_weight_p95, 0)}.` },
    { eyebrow: "The map", kind: "ARITHMETIC",
      title: `Redrawing cuts workload imbalance from ${mult(terr?.imbalance_before, 0)} to ${mult(terr?.imbalance_after, 1)}, every territory contiguous`,
      body: territories.data ? <MiniMap units={territories.data.units} /> : null,
      points: [`Contiguity ${pct(terr?.contiguity_before, 0)} → ${pct(terr?.contiguity_after, 0)}`,
        `Travel ${pct(terr?.travel_reduction_pct, 0)} shorter`,
        `Plain k-means leaves ${mult(terr?.kmeans_imbalance, 0)} imbalance: compact is not workable`],
      soWhat: "Redraw with the list change, so reps meet new targets inside a fair territory." },
    { eyebrow: "Headcount", kind: "SCENARIO",
      title: `Today's 60th rep pays only if calls capture ${pct(d?.headline.required_ceiling_at_current, 2)} of headroom a year`,
      body: d ? <HeadcountExplorer data={d} /> : null,
      soWhat: "Do not hire or cut on a number nobody has measured. Measure it." },
    { eyebrow: "The business case", kind: "SCENARIO",
      title: "The pilot beats every decision made blind, for any belief a sceptic and a believer can share",
      body: d ? <BeliefExplorer data={d} /> : null,
      soWhat: "The pilot is the expected-value choice and the robust one: approve it." },
    { eyebrow: "The pilot", kind: "SCENARIO",
      title: "Scored on share points, a two-quarter hold-out finds the answer; scored on fills it cannot",
      body: d ? <PilotPower pilot={d.pilot} /> : null,
      soWhat: `Fix the endpoint before launch: ${pct(sh?.power_holdout20_6m, 0)} power on share points vs ${pct(fl?.power_holdout20_6m, 0)} on fills.` },
    { eyebrow: "Roadmap and the ask", title: "Thirty-six weeks to a measured headcount decision. Three approvals today.", dark: true,
      body: <Ask robust={fr?.robust_weight_p95} /> },
  ];

  const n = slides.length;
  const go = useCallback((k: number) => setI(Math.max(0, Math.min(n - 1, k))), [n]);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement | null)?.tagName === "INPUT") return;
      if (["ArrowRight", "PageDown", " "].includes(e.key)) { e.preventDefault(); go(i + 1); }
      else if (["ArrowLeft", "PageUp"].includes(e.key)) { e.preventDefault(); go(i - 1); }
      else if (e.key === "Home") go(0);
      else if (e.key === "End") go(n - 1);
      else if (e.key === "Escape") nav("/app");
      else if (e.key.toLowerCase() === "f") void document.documentElement.requestFullscreen?.().catch(() => undefined);
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [i, go, n, nav]);

  useEffect(() => {
    window.history.replaceState(null, "", `?s=${i + 1}`);
  }, [i]);

  return (
    <div className="brief min-h-screen bg-plum text-ink">
      <style>{BRIEF_CSS}</style>
      {/* One slide mounted at a time, keyed by index, so every exhibit plays its
          entrance when its slide arrives rather than off-screen. The PDF deck is
          the printable version. */}
      <section key={i} className={`brief-slide ${slides[i]!.dark ? "slab" : ""}`}
        aria-label={`Slide ${i + 1} of ${n}`}>
        <SlideView sl={slides[i]!} k={i} n={n} />
      </section>

      <nav className="brief-nav" aria-label="Slides">
        <button type="button" onClick={() => go(i - 1)} disabled={i === 0} aria-label="Previous slide">←</button>
        <div className="flex gap-1.5">
          {slides.map((_, k) => (
            <button key={k} type="button" onClick={() => go(k)} aria-label={`Go to slide ${k + 1}`}
              className="h-2 rounded-full transition-all duration-base"
              style={{ width: k === i ? 26 : 8, background: k === i ? "var(--terracotta)" : "rgba(248,238,234,.35)" }} />
          ))}
        </div>
        <button type="button" onClick={() => go(i + 1)} disabled={i === n - 1} aria-label="Next slide">→</button>
        <span className="num ml-2 text-[12px]" style={{ color: "var(--text-mute)" }}>{i + 1} / {n}</span>
        <span className="mx-2 h-4 w-px" style={{ background: "rgba(248,238,234,.2)" }} />
        <a href="/api/download/executive" className="brief-link">Deck PDF</a>
        <a href="/api/download/onepager" className="brief-link">One-pager</a>
        <Link to="/app" className="brief-link">Exit</Link>
      </nav>
    </div>
  );
}

function SlideView({ sl, k, n }: { sl: Slide; k: number; n: number }) {
  return (
    <div className="mx-auto flex h-full max-w-[1400px] flex-col px-6 py-8 sm:px-12 sm:py-10">
      <header className="flex items-center justify-between">
        <span className="flex items-center gap-3">
          <span className="eyebrow" style={sl.dark ? { color: "var(--mauve)" } : undefined}>{sl.eyebrow}</span>
          {sl.kind && <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
            style={{ background: "color-mix(in oklab, var(--terracotta) 14%, transparent)", color: "var(--terracotta-ink)" }}>{sl.kind}</span>}
        </span>
        <span className="num text-[12px] text-ink-faint">{String(k + 1).padStart(2, "0")} / {String(n).padStart(2, "0")}</span>
      </header>
      <h1 className={`mt-3 max-w-[30ch] font-display font-bold leading-[1.08] tracking-[-0.015em] ${k === 0 ? "display text-[clamp(3rem,8vw,7rem)]" : "text-[clamp(1.6rem,3vw,2.7rem)]"}`}
        style={k === 0 ? { color: "var(--text-hi)" } : undefined}>
        {k === 0 ? <>Target the <span style={{ color: "var(--terracotta-hi)" }}>gap</span>,<br />not the <span className="serif-i" style={{ color: "var(--mauve)" }}>volume.</span></> : sl.title}
      </h1>
      <div className={`mt-6 grid flex-1 gap-8 ${sl.points ? "xl:grid-cols-[1fr_320px]" : ""}`}>
        <div className="min-w-0">{sl.body}</div>
        {sl.points && (
          <ol className="space-y-5 self-start">
            {sl.points.map((p, j) => (
              <li key={j} className="flex gap-3">
                <span className="font-display text-[28px] font-bold leading-none" style={{ color: "var(--terracotta)" }}>{j + 1}</span>
                <span className="pt-1 text-[15px] leading-snug">{p}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
      {sl.soWhat && (
        <p className="mt-6 rounded-xl border-l-4 px-5 py-3 text-[15px]"
          style={{ borderColor: "var(--terracotta)", background: "var(--rule-soft)" }}>
          <strong className="mr-3 text-[11px] uppercase tracking-[0.14em]" style={{ color: "var(--terracotta-ink)" }}>So what</strong>
          {sl.soWhat}
        </p>
      )}
    </div>
  );
}

function TitleBody({ rec, imb, power }: { rec?: number; imb: (number | undefined)[]; power?: number }) {
  return (
    <div className="grid gap-10 lg:grid-cols-[1.2fr_1fr]">
      <p className="max-w-[52ch] text-[20px] leading-relaxed" style={{ color: "var(--text)" }}>
        Same 60 reps, same cost: re-target the calls, redraw the map, and measure what a call is worth
        before changing headcount.
      </p>
      <ol className="space-y-6">
        {[["01", "Re-target", `${mult(rec)} share gains`], ["02", "Redraw", `${mult(imb[0], 0)} → ${mult(imb[1], 1)} imbalance`],
          ["03", "Pilot", `${pct(power, 0)} power, two quarters`]].map(([a, b, c]) => (
          <li key={a} className="flex items-baseline gap-4">
            <span className="display text-[40px]" style={{ color: "var(--terracotta-hi)" }}>{a}</span>
            <span><span className="block text-[20px] font-semibold" style={{ color: "var(--text-hi)" }}>{b}</span>
              <span className="text-[14px]" style={{ color: "var(--mauve)" }}>{c}</span></span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Summary({ rows, stack }: { rows: [string, string, string, string][]; stack: [string, string][] }) {
  return (
    <div className="flex h-full flex-col gap-6">
      <div className="grid gap-4 md:grid-cols-3">
        {rows.map(([tag, col, head, body]) => (
          <div key={head} className="card p-6">
            <span className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold text-white" style={{ background: col }}>{tag}</span>
            <h3 className="font-display mt-4 text-[24px] font-bold leading-tight">{head}</h3>
            <p className="mt-2 text-[15px] text-ink-mute">{body}</p>
          </div>
        ))}
      </div>
      <div className="slab grid gap-6 p-6 sm:grid-cols-2 lg:grid-cols-4">
        {stack.map(([v, k]) => (
          <div key={k}>
            <div className="num text-[30px] font-semibold" style={{ color: "var(--terracotta-hi)" }}>{v}</div>
            <div className="text-small" style={{ color: "var(--text)" }}>{k}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MiniMap({ units }: { units: { lat: number; lon: number; workload: number; territory: number }[] }) {
  const us = units.filter((u) => u.lat > 24 && u.lat < 50 && u.lon > -125 && u.lon < -66);
  const load = new Map<number, number>();
  for (const u of us) load.set(u.territory, (load.get(u.territory) ?? 0) + u.workload);
  const vals = [...load.values()].sort((a, b) => a - b);
  const lo = vals[Math.floor(vals.length * 0.05)] ?? 0;
  const hi = vals[Math.floor(vals.length * 0.95)] ?? 1;
  const ramp = ["#EADFE3", "#C3A0A7", "#C75A3A", "#3A1F34"];
  const col = (v: number) => ramp[Math.max(0, Math.min(3, Math.floor(((v - lo) / (hi - lo || 1)) * 3.99)))]!;
  const W = 900;
  const H = 500;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Optimised territories, coloured by workload.">
      {us.map((u, k) => (
        <circle key={k} cx={((u.lon + 125) / 59) * W} cy={(1 - (u.lat - 24) / 26) * H} r={5}
          fill={col(load.get(u.territory) ?? 0)} opacity={0.9}
          style={{ animation: `pop 500ms ${(k % 120) * 6}ms both` }} />
      ))}
    </svg>
  );
}

function Ask({ robust }: { robust?: number }) {
  const asks = [
    ["Approve the blended call list", "Same reps, same budget; CRM change in four weeks."],
    ["Approve the territory redraw", "Phased hand-over; top accounts stay with their rep."],
    ["Freeze headcount at 60 for two quarters", "And fund the 20% hold-out; the month-six read-out decides the size."],
  ];
  const kills = [
    "Pilot effect < 0.5× break-even → redeploy or shrink through attrition",
    "Pilot effect > 2× break-even → reopen hiring with a measured number",
    `Blend below the 90% floor at a refresh → move to ${pct(robust, 0)} weight`,
    "Call compliance < 80% → fix adoption before reading any result",
  ];
  return (
    <div className="grid gap-10 lg:grid-cols-[1.1fr_1fr]">
      <ol className="space-y-7">
        {asks.map(([a, b], j) => (
          <li key={a} className="flex gap-5">
            <span className="display text-[46px] leading-none" style={{ color: "var(--terracotta-hi)" }}>{j + 1}</span>
            <span><span className="block text-[22px] font-semibold" style={{ color: "var(--text-hi)" }}>{a}</span>
              <span className="text-[15px]" style={{ color: "var(--text)" }}>{b}</span></span>
          </li>
        ))}
      </ol>
      <div>
        <p className="eyebrow" style={{ color: "var(--mauve)" }}>Kill criteria</p>
        <ul className="mt-3 space-y-3">
          {kills.map((k) => (
            <li key={k} className="border-b pb-3 text-[15px]" style={{ borderColor: "rgba(248,238,234,.14)", color: "var(--text)" }}>
              <span style={{ color: "var(--terracotta-hi)" }}>IF </span>{k}
            </li>
          ))}
        </ul>
        <p className="mt-6 text-small" style={{ color: "var(--text-mute)" }}>
          Weeks 0–2 sign-off · 2–6 list and hold-out · 6–14 redraw · 6–32 pilot · 32–36 decide
        </p>
      </div>
    </div>
  );
}

const BRIEF_CSS = `
.brief { position: relative; }
.brief-slide { position: fixed; inset: 0 0 64px 0; overflow-y: auto;
  animation: slide-in 560ms cubic-bezier(.16,1,.3,1) both; }
.brief-slide:not(.slab) { background: var(--paper); }
.brief-slide.slab { border-radius: 0; }
@keyframes slide-in { from { opacity: 0; transform: translateX(48px) scale(.985); } to { opacity: 1; transform: none; } }
.brief-nav { position: fixed; left: 0; right: 0; bottom: 0; height: 64px; display: flex; align-items: center;
  justify-content: center; gap: 14px; background: var(--plum); color: var(--text-hi); z-index: 10; }
.brief-nav > button { width: 36px; height: 36px; border-radius: 999px; border: 1px solid rgba(248,238,234,.25); }
.brief-nav > button:disabled { opacity: .3; }
.brief-link { color: var(--text-mute); font-size: 12px; text-decoration: none; }
.brief-link:hover { color: var(--terracotta-hi); }
@keyframes pop { from { opacity: 0; transform: scale(.2); } to { opacity: .9; transform: none; } }
@media (prefers-reduced-motion: reduce) { .brief-slide { animation: none; } }
`;
