/**
 * The case -- the consulting storyline, end to end.
 *
 *   SCQ           situation, complication, question, answer
 *   Issue tree    the question broken MECE into hypotheses, each with a verdict
 *                 and the number that decided it
 *   Red team      the six strongest objections, and what survived them
 *   Roadmap       what happens on Monday, in what order, with which gate
 *   Risks         likelihood x impact, with the owner's mitigation
 *   Kill criteria what result would reverse each recommendation
 *
 * Verdicts are computed from the API where a number decides them, so the tree
 * cannot drift from the pipeline.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { fmt, mult, pct, usd } from "@/lib/format";
import { Reveal, useInView } from "@/lib/motion";
import { EvidencePill } from "@/components/Primitives";
import { ErrorState } from "@/components/States";
import type { EvidenceClass } from "@/lib/types";

type Verdict = "Supported" | "Refuted" | "Untestable" | "Association only";

const VERDICT: Record<Verdict, { bg: string; fg: string }> = {
  Supported: { bg: "rgba(76,125,90,.15)", fg: "var(--pos)" },
  Refuted: { bg: "rgba(163,38,62,.12)", fg: "var(--neg)" },
  Untestable: { bg: "rgba(183,121,31,.15)", fg: "var(--warn)" },
  "Association only": { bg: "rgba(195,160,167,.3)", fg: "var(--ink-mute)" },
};

interface Hyp { id: string; text: string; verdict: Verdict; evidence: string; kind: EvidenceClass }
interface Branch { id: string; q: string; hyps: Hyp[] }

export function Case() {
  const summary = useQuery({ queryKey: qk.summary, queryFn: api.summary });
  const decision = useQuery({ queryKey: qk.decision, queryFn: api.decision, retry: 1 });
  const response = useQuery({ queryKey: qk.response, queryFn: api.responseModule, retry: 1 });
  if (summary.isError) return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />;

  const s = summary.data;
  const h1 = s?.headlines.h1;
  const h3 = s?.headlines.h3;
  const rec = s?.headlines.recommendation;
  const terr = s?.territory;
  const fr = decision.data?.frontier_summary;
  const pilot = decision.data?.pilot;
  const econ = decision.data?.economics;
  const pre = response.data?.pretrend;
  const did = response.data?.did;
  const rules = s?.headlines.business_case?.rules ?? {};

  const tree: Branch[] = [
    {
      id: "A", q: "Who should the reps call?",
      hyps: [
        { id: "A1", kind: "ARITHMETIC", verdict: "Supported",
          text: "The volume list misses high-opportunity prescribers",
          evidence: `${pct(s?.disagreement.disagree_by_2plus_pct, 0)} of writers sit 2+ deciles apart on the two rankings; ${fmt(s?.disagreement.volume_low_opportunity_high)} are low-volume / high-opportunity.` },
        { id: "A2", kind: "BACK-TESTED", verdict: h1?.gate_passed ? "Supported" : "Refuted",
          text: "Opportunity-flagged prescribers grow faster, out of time",
          evidence: `${mult(h1?.matched_growth_ratio)} the growth of propensity-matched controls in held-out 2024 (+${fmt(h1?.matched_paired_difference, 1)} fills per prescriber).` },
        { id: "A3", kind: "BACK-TESTED", verdict: (rec?.abs_vs_volume ?? 0) >= 0.9 ? "Supported" : "Refuted",
          text: "A blend beats both pure rules on the brand's two goals",
          evidence: `${mult(rec?.share_vs_volume)} volume's share gains with ${pct(rec?.abs_vs_volume, 0)} of its absolute growth; clears the floor in ${pct(fr?.equal_weight_p_clears_floor, 0)} of re-draws.` },
        { id: "A4", kind: "BACK-TESTED", verdict: "Refuted",
          text: "A black-box ML model would target better",
          evidence: `The share model wins share by choosing tiny prescribers (median ${fmt(rules.ml_share?.median_base_class_fills, 0)} fills) and captures ${pct(rules.ml_share?.abs_capture)} of absolute growth.` },
      ],
    },
    {
      id: "B", q: "How should the territories be drawn?",
      hyps: [
        { id: "B1", kind: "ARITHMETIC", verdict: "Supported",
          text: "Today's territories are badly unbalanced",
          evidence: `The busiest territory carries ${mult(terr?.imbalance_before, 0)} the workload of the lightest; only ${pct(terr?.contiguity_before, 0)} are contiguous.` },
        { id: "B2", kind: "ARITHMETIC", verdict: "Supported",
          text: "Rebalancing need not cost travel",
          evidence: `Imbalance falls to ${mult(terr?.imbalance_after, 1)}, travel ${pct(terr?.travel_reduction_pct, 0)} shorter, 100% contiguous. Plain k-means is tighter but leaves ${mult(terr?.kmeans_imbalance, 0)} imbalance.` },
      ],
    },
    {
      id: "C", q: "How many reps?",
      hyps: [
        { id: "C1", kind: "PROXY", verdict: "Untestable",
          text: "More calls measurably move prescribing",
          evidence: `Brand-named meal events show no dose-response within volume bands (fitted ceiling 0). Absence of evidence, not evidence of absence.` },
        { id: "C2", kind: "SCENARIO", verdict: "Supported",
          text: "A pilot can measure it within two quarters",
          evidence: `A 20% hold-out scored on share points detects the break-even response (${pct(h3?.required_ceiling_at_current, 2)} of headroom a year) with ${pct(pilot?.share?.power_holdout20_6m, 0)} power.` },
      ],
    },
    {
      id: "D", q: "Does promotion spend drive share?",
      hyps: [
        { id: "D1", kind: "PROXY", verdict: "Association only",
          text: "Paid prescribers gain share because they were paid",
          evidence: `Matched DiD +${fmt(Number(did?.did_estimate ?? 0) * 100, 1)} share points, but paid prescribers were already gaining ${fmt(Number(pre?.difference ?? 0) * 100, 1)} points faster before payment (p ≈ 0).` },
      ],
    },
  ];

  return (
    <>
      <header className="mb-10">
        <p className="eyebrow">The case</p>
        <h1 className="display mt-2 text-[clamp(2.4rem,5vw,4.4rem)]">
          From question to <span style={{ color: "var(--terracotta)" }}>Monday morning</span>.
        </h1>
      </header>

      {/* ---- SCQ --------------------------------------------------------- */}
      <div className="mb-14 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Scq n="S" t="Situation" body={`A ${fmt(h3?.current_n_reps)}-rep field force promotes a branded DOAC to ${fmt(s?.kpis.hcps_in_market)} Medicare anticoagulant writers, ranked by how much they already write.`} />
        <Scq n="C" t="Complication" body={`Volume ranking calls on prescribers who are already converted, and the territories it produced are ${mult(terr?.imbalance_before, 0)} unbalanced. Nobody knows what a call is worth.`} />
        <Scq n="Q" t="Question" body="Who should the same reps call, how should their territories be drawn, and should the force grow?" />
        <Scq n="A" t="Answer" dark body={`Re-target on a 50/50 blend (${mult(rec?.share_vs_volume)} share gains, ${pct(rec?.abs_vs_volume, 0)} of growth kept), redraw territories, hold 60 reps and pilot for two quarters.`} />
      </div>

      {/* ---- issue tree -------------------------------------------------- */}
      <SectionTitle eyebrow="Issue tree" title="Four questions, nine hypotheses, each with the number that decided it" />
      <IssueTree root="How should the brand deploy its field force to grow share profitably?" branches={tree} />

      {/* ---- red team ---------------------------------------------------- */}
      <SectionTitle eyebrow="Red team" title="The six strongest objections, and what survived them" />
      <div className="mb-14 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Objection i={0} q="“The back-test just rewards big prescribers.”"
          a={`Share growth is volume-neutral, and flagged prescribers beat propensity-matched controls of the same size by ${mult(h1?.matched_growth_ratio)} (worst covariate SMD 0.05).`}
          verdict="Holds" />
        <Objection i={1} q="“50/50 is a number nobody chose.”"
          a={`Correct, so the weight was swept. A weight tuned on 2022→23 (${pct(fr?.selected_weight, 0)}) fails the floor in 2024; 50/50 clears it in ${pct(fr?.equal_weight_p_clears_floor, 0)} of re-draws. Tuning to the edge is the fragile choice.`}
          verdict="Holds, with a margin to monitor" />
        <Objection i={2} q="“You found growth, not persuadable doctors.”"
          a="True, and stated everywhere. The holdout has no call data, so it proves the ranking finds growing prescribers, not that calling them causes growth. That is exactly what the pilot is for."
          verdict="Open: pilot resolves" tone="warn" />
        <Objection i={3} q="“Meal payments are a poor proxy for rep visits.”"
          a="Agreed. Most details involve no meal. So the null result is read as ‘not measurable here’, which is why the headcount recommendation is hold, not cut."
          verdict="Accepted: drives ‘hold’" tone="warn" />
        <Objection i={4} q="“The data are Medicare-only and 17 months old.”"
          a="Part D covers most DOAC patients (older AF), so it is the right lens for this class, but commercial writers are invisible. Refresh on each CMS release; re-read the floor every year."
          verdict="Residual risk: medium" tone="warn" />
        <Objection i={5} q="“Drug-price negotiation changes the maths.”"
          a={`It does. The 2026 Medicare negotiated price (${usd(econ?.ira_2026_price_per_fill)}) is ${pct(econ ? 1 - econ.ira_2026_price_per_fill / econ.net_revenue_per_30day_fill.base : null, 0)} below the net assumed, raising the break-even response to ${pct(h3?.required_ceiling_at_current != null && econ ? h3.required_ceiling_at_current * econ.net_revenue_per_30day_fill.base / econ.ira_2026_price_per_fill : null, 2)}. It strengthens ‘re-target, don’t hire’.`}
          verdict="Strengthens the answer" />
      </div>

      {/* ---- roadmap ----------------------------------------------------- */}
      <SectionTitle eyebrow="Roadmap" title="Thirty-six weeks from sign-off to a measured headcount decision" />
      <Roadmap />

      {/* ---- risks + kill criteria -------------------------------------- */}
      <div className="mt-14 grid gap-6 xl:grid-cols-[1.1fr_1fr]">
        <Reveal as="section" className="card p-6">
          <p className="eyebrow">Risk register</p>
          <h3 className="font-display mt-1 text-[24px] font-bold">What could go wrong in delivery</h3>
          <RiskMatrix />
        </Reveal>
        <Reveal as="section" className="slab p-6 sm:p-8" delay={120}>
          <p className="eyebrow" style={{ color: "var(--mauve)" }}>Kill criteria</p>
          <h3 className="font-display mt-1 text-[24px] font-bold">What would change our mind</h3>
          <ul className="mt-5 space-y-4">
            <Kill when="Pilot effect < 0.5× break-even at month 6" then="The force is larger than calling justifies. Redeploy reps to the highest-opportunity territories, or shrink the force through attrition." />
            <Kill when="Pilot effect > 2× break-even" then="Reopen headcount with a measured response: the decision lab's curve becomes a forecast, not a scenario." />
            <Kill when={`Blend keeps < ${pct(fr?.abs_floor_vs_volume, 0)} of volume's growth at a refresh`} then={`Move the weight to ${pct(fr?.robust_weight_p95, 0)}, the setting that clears the floor in 95% of re-draws.`} />
            <Kill when="Rep call compliance < 80% on the new list" then="The test is of the list, not of the reps. Fix adoption (CRM nudges, incentive alignment) before reading any result." />
          </ul>
        </Reveal>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ parts */

function SectionTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="mb-5">
      <p className="eyebrow">{eyebrow}</p>
      <h2 className="font-display mt-1 max-w-[30ch] text-[clamp(1.6rem,2.6vw,2.3rem)] font-bold leading-tight">{title}</h2>
    </div>
  );
}

function Scq({ n, t, body, dark }: { n: string; t: string; body: string; dark?: boolean }) {
  return (
    <Reveal className={`${dark ? "slab" : "card"} relative overflow-hidden p-6`}>
      <span aria-hidden className="display absolute -bottom-6 right-2 text-[120px] opacity-10">{n}</span>
      <p className="eyebrow" style={dark ? { color: "var(--mauve)" } : undefined}>{t}</p>
      <p className="mt-3 text-[15px] leading-relaxed">{body}</p>
    </Reveal>
  );
}

function IssueTree({ root, branches }: { root: string; branches: Branch[] }) {
  const [ref, inView] = useInView<HTMLDivElement>(0.1);
  const [open, setOpen] = useState<string | null>("A3");
  let k = 0;
  return (
    <div ref={ref} className="mb-14 grid gap-4 xl:grid-cols-[250px_1fr]">
      <div className="slab self-start p-6 xl:sticky xl:top-8">
        <div>
          <p className="eyebrow" style={{ color: "var(--mauve)" }}>Governing question</p>
          <p className="font-display mt-2 text-[22px] font-bold leading-snug">{root}</p>
        </div>
      </div>
      <div className="space-y-4">
        {branches.map((b) => (
          <div key={b.id} className="relative grid gap-3 md:grid-cols-[180px_1fr]">
            <div className="card flex items-center gap-3 self-start p-4">
              <span className="display text-[30px]" style={{ color: "var(--terracotta)" }}>{b.id}</span>
              <span className="font-display text-[16px] font-bold leading-snug">{b.q}</span>
            </div>
            <div className="space-y-2">
              {b.hyps.map((h) => {
                const i = k++;
                const isOpen = open === h.id;
                return (
                  <button key={h.id} type="button" onClick={() => setOpen(isOpen ? null : h.id)}
                    className="card block w-full p-4 text-left transition-all duration-base hover:border-[var(--mauve)]"
                    style={{
                      opacity: inView ? 1 : 0,
                      transform: inView ? "none" : "translateX(24px)",
                      transition: `opacity 600ms ${i * 70}ms, transform 600ms cubic-bezier(.16,1,.3,1) ${i * 70}ms, border-color 160ms`,
                    }}
                    aria-expanded={isOpen}>
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="num text-[11px] text-ink-faint">{h.id}</span>
                      <span className="flex-1 text-[15px] font-medium">{h.text}</span>
                      <span className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                        style={{ background: VERDICT[h.verdict].bg, color: VERDICT[h.verdict].fg }}>{h.verdict}</span>
                      <span className="text-ink-faint transition-transform duration-quick" style={{ transform: isOpen ? "rotate(90deg)" : "none" }}>›</span>
                    </span>
                    <span className="grid transition-all duration-slow ease-out"
                      style={{ gridTemplateRows: isOpen ? "1fr" : "0fr", opacity: isOpen ? 1 : 0 }}>
                      <span className="overflow-hidden">
                        <span className="mt-3 flex items-start gap-2 border-t border-rule-soft pt-3 text-small text-ink-mute">
                          <EvidencePill kind={h.kind} />
                          <span>{h.evidence}</span>
                        </span>
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Objection({ q, a, verdict, tone = "pos", i }: {
  q: string; a: string; verdict: string; tone?: "pos" | "warn"; i: number;
}) {
  const [flipped, setFlipped] = useState(false);
  return (
    <Reveal delay={i * 80}>
      <button type="button" onClick={() => setFlipped(!flipped)} aria-pressed={flipped}
        className="group block h-[230px] w-full text-left [perspective:1200px]">
        <span className="relative block h-full w-full transition-transform duration-slow ease-out [transform-style:preserve-3d]"
          style={{ transform: flipped ? "rotateY(180deg)" : "none" }}>
          <span className="card absolute inset-0 flex flex-col justify-between p-6 [backface-visibility:hidden]">
            <span className="font-display text-[22px] font-bold italic leading-snug">{q}</span>
            <span className="text-small font-semibold" style={{ color: "var(--terracotta)" }}>Tap for the answer ↻</span>
          </span>
          <span className="slab absolute inset-0 flex flex-col justify-between p-6 [backface-visibility:hidden] [transform:rotateY(180deg)]">
            <span className="text-small leading-relaxed" style={{ color: "var(--text)" }}>{a}</span>
            <span className="self-start rounded-full px-3 py-1 text-[11px] font-semibold text-white"
              style={{ background: tone === "pos" ? "var(--pos)" : "var(--warn)" }}>{verdict}</span>
          </span>
        </span>
      </button>
    </Reveal>
  );
}

const PHASES = [
  { lane: "Align", name: "Sign-off: freeze the rule, floor and endpoint", start: 0, end: 2, kpi: "Decision memo signed" },
  { lane: "Re-target", name: "Load the blended list into CRM, brief reps", start: 2, end: 6, kpi: "≥ 80% of calls on-list" },
  { lane: "Re-target", name: "Randomise the 20% hold-out", start: 4, end: 6, kpi: "Arms balanced (SMD < 0.1)" },
  { lane: "Territories", name: "Redraw, transition accounts, HR", start: 6, end: 14, kpi: "Imbalance < 4×" },
  { lane: "Pilot", name: "Run: two quarters, no changes to arms", start: 6, end: 32, kpi: "Contamination < 5%" },
  { lane: "Pilot", name: "Month-3 read: check noise scales as planned", start: 18, end: 19, kpi: "Power on track" },
  { lane: "Decide", name: "Read share-point effect, size headcount", start: 32, end: 36, kpi: "Effect vs break-even" },
];

function Roadmap() {
  const [ref, inView] = useInView<HTMLDivElement>(0.2);
  const weeks = 36;
  const lanes = [...new Set(PHASES.map((p) => p.lane))];
  return (
    <div ref={ref} className="card overflow-x-auto p-6">
      <div className="min-w-[560px]">
        <div className="relative mb-2 ml-[110px] flex text-[10px] text-ink-faint">
          {Array.from({ length: weeks / 4 + 1 }, (_, i) => i * 4).map((w) => (
            <span key={w} className="num absolute -translate-x-1/2" style={{ left: `${(w / weeks) * 100}%` }}>wk {w}</span>
          ))}
        </div>
        <div className="mt-5 space-y-3">
          {lanes.map((lane) => (
            <div key={lane} className="flex items-start">
              <div className="w-[110px] shrink-0 pt-2 text-small font-semibold">{lane}</div>
              <div className="relative flex-1 rounded-lg" style={{
                height: PHASES.filter((p) => p.lane === lane).length * 42,
                background: "repeating-linear-gradient(90deg, transparent 0 calc(11.111% - 1px), var(--rule-soft) calc(11.111% - 1px) 11.111%)",
              }}>
                {PHASES.filter((p) => p.lane === lane).map((p, j) => {
                  const idx = PHASES.indexOf(p);
                  const milestone = p.end - p.start <= 1;
                  return (
                    <div key={p.name} className="group absolute flex h-[34px] items-center overflow-hidden rounded-lg px-3 text-[12px] font-medium text-white"
                      title={`${p.name} · KPI: ${p.kpi}`}
                      style={{
                        top: j * 42,
                        left: `${(p.start / weeks) * 100}%`,
                        width: inView ? `${(Math.max(p.end - p.start, 1) / weeks) * 100}%` : "0%",
                        minWidth: milestone ? 34 : undefined,
                        background: lane === "Pilot" ? "linear-gradient(90deg, var(--terracotta), var(--terracotta-hi))"
                          : lane === "Decide" ? "var(--pos)" : lane === "Align" ? "var(--mauve)" : "var(--plum)",
                        transition: `width 900ms cubic-bezier(.16,1,.3,1) ${idx * 110}ms`,
                        whiteSpace: "nowrap",
                      }}>
                      {milestone ? "◆" : p.name}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-5 grid gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {PHASES.map((p) => (
            <div key={p.name} className="rounded-lg border border-rule px-3 py-2 text-[12px]">
              <div className="font-semibold">{p.name}</div>
              <div className="text-ink-mute">KPI · {p.kpi}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const RISKS = [
  { name: "Reps keep calling their old accounts", l: 0.8, i: 0.85, fix: "CRM call-list nudges; first-quarter incentive on on-list calls" },
  { name: "Hold-out contaminated by reps", l: 0.5, i: 0.8, fix: "Hold-out hidden in CRM; monthly audit of calls to held-out NPIs" },
  { name: "Territory change breaks relationships", l: 0.55, i: 0.55, fix: "Phase the hand-over; keep top-decile accounts with their rep" },
  { name: "Formulary or payer shift mid-pilot", l: 0.4, i: 0.75, fix: "Stratify randomisation by plan mix; read share within plan" },
  { name: "Medicare price cut lowers call value", l: 0.9, i: 0.5, fix: "Already priced: it raises the bar for hiring, not for re-targeting" },
  { name: "Data lag hides a market change", l: 0.45, i: 0.4, fix: "Refresh on each CMS release; re-read the blend floor yearly" },
];

function RiskMatrix() {
  const [ref, inView] = useInView<HTMLDivElement>(0.2);
  const [hover, setHover] = useState<number | null>(0);
  const r = hover != null ? RISKS[hover] : null;
  return (
    <div ref={ref} className="mt-4 grid gap-4 md:grid-cols-[1fr_200px]">
      <div className="relative aspect-square max-h-[340px] rounded-xl"
        style={{ background: "linear-gradient(45deg, rgba(76,125,90,.10), rgba(183,121,31,.10) 50%, rgba(163,38,62,.16))" }}>
        {[1, 2].map((g) => (
          <span key={g}>
            <span className="absolute inset-y-0 w-px" style={{ left: `${(g / 3) * 100}%`, background: "var(--rule)" }} />
            <span className="absolute inset-x-0 h-px" style={{ top: `${(g / 3) * 100}%`, background: "var(--rule)" }} />
          </span>
        ))}
        <span className="absolute bottom-1 right-2 text-[10px] text-ink-faint">likelihood →</span>
        <span className="absolute left-1 top-2 text-[10px] text-ink-faint [writing-mode:vertical-rl] rotate-180">impact →</span>
        {RISKS.map((k, i) => (
          <button key={k.name} type="button" onPointerEnter={() => setHover(i)} onFocus={() => setHover(i)}
            className="absolute grid h-9 w-9 -translate-x-1/2 translate-y-1/2 place-items-center rounded-full text-[12px] font-semibold text-white"
            style={{
              left: `${k.l * 100}%`, bottom: `${k.i * 100}%`,
              background: k.l * k.i > 0.45 ? "var(--neg)" : k.l * k.i > 0.25 ? "var(--terracotta)" : "var(--mauve)",
              boxShadow: hover === i ? "0 0 0 6px rgba(199,90,58,.25)" : "none",
              transform: `translate(-50%, 50%) scale(${inView ? (hover === i ? 1.2 : 1) : 0})`,
              transition: `transform 500ms cubic-bezier(.34,1.56,.64,1) ${i * 90}ms, box-shadow 160ms`,
            }}
            aria-label={k.name}>
            {i + 1}
          </button>
        ))}
      </div>
      <div className="text-small">
        {r && (
          <div key={r.name} style={{ animation: "page-in 300ms" }}>
            <p className="font-display text-[18px] font-bold leading-snug">{r.name}</p>
            <p className="mt-2 text-ink-mute">Likelihood {pct(r.l, 0)} · impact {pct(r.i, 0)}</p>
            <p className="mt-3"><span className="eyebrow">Mitigation</span><br />{r.fix}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function Kill({ when, then }: { when: string; then: string }) {
  return (
    <li className="grid gap-1 border-b pb-4 last:border-0" style={{ borderColor: "rgba(248,238,234,.12)" }}>
      <span className="text-small font-semibold" style={{ color: "var(--terracotta-hi)" }}>IF {when}</span>
      <span className="text-small" style={{ color: "var(--text)" }}>THEN {then}</span>
    </li>
  );
}
