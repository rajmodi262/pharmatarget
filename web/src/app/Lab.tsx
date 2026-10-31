/**
 * Decision lab -- the three questions a partner asks after the deck.
 *
 *   1. Is 50/50 the right blend, or a number nobody chose?
 *   2. How many reps -- and what would have to be true to change that?
 *   3. Can the pilot we recommend actually find the answer?
 *
 * Each is answered by an exhibit the reader can drag, computed from the
 * pipeline's own anchors (src/models/decision.py, sizing.py), so a sceptic can
 * test the recommendation's edges instead of taking them on trust.
 */

import { useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { mult, pct, usd } from "@/lib/format";
import { Reveal } from "@/lib/motion";
import { Caveat, SectionHead } from "@/components/Primitives";
import { ErrorState, SkeletonChart } from "@/components/States";
import { FrontierChart } from "@/components/viz/FrontierChart";
import { HeadcountExplorer } from "@/components/viz/HeadcountExplorer";
import { PilotPower } from "@/components/viz/PilotPower";
import { BeliefExplorer, PayoffMatrix } from "@/components/viz/BusinessCase";

export function Lab() {
  const q = useQuery({ queryKey: qk.decision, queryFn: api.decision });
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const d = q.data;
  const fr = d?.frontier_summary;
  const sh = d?.pilot.share;
  const fi = d?.pilot.fills;
  const robust = d?.frontier.find((r) => r.period === "holdout" && r.weight === fr?.robust_weight_p95);
  const eqSel = d?.frontier.find((r) => r.period === "selection" && r.weight === 0.5);
  const floor = fr?.abs_floor_vs_volume ?? 0.9;
  const bc = d?.business_case;
  const rt = bc?.retargeting_per_year_by_response;

  return (
    <>
      <header className="mb-10">
        <p className="eyebrow">Decision lab</p>
        <h1 className="display mt-2 text-[clamp(2.4rem,5vw,4.4rem)]">
          Push on the answer<span style={{ color: "var(--terracotta)" }}>.</span>
        </h1>
        <p className="serif-i mt-3 max-w-[60ch] text-[20px] leading-snug text-ink-mute">
          Three questions a partner asks in the first ten minutes. Each answer is an exhibit you
          can drag, computed from the pipeline&apos;s own numbers.
        </p>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <QCard n="Q1" q="Is 50/50 the right blend?" a={fr ? `Yes, and not by tuning: a tuned ${pct(fr.selected_weight, 0)} fails out of time` : "…"} />
          <QCard n="Q2" q="How many reps?" a="Hold 60: the response that would justify more is not measurable yet" />
          <QCard n="Q3" q="Can a pilot settle it?" a={sh ? `Yes, if scored on share points: ${pct(sh.power_holdout20_6m, 0)} power in 6 months` : "…"} />
          <QCard n="Q4" q="What is it all worth?" a={bc?.base_pilot_value != null ? `Re-targeting ${usd(rt?.["1.0"])}/yr at no cost; the pilot adds ${usd(bc.base_pilot_value)} over holding blind` : "…"} />
        </div>
      </header>

      {/* ---- Q1 ---------------------------------------------------------- */}
      <Reveal as="section" className="card mb-8 p-6 sm:p-8">
        <SectionHead eyebrow="Q1 · Blend frontier" kind="BACK-TESTED"
          title="The weight you would tune on last year falls through the floor this year. Equal weight holds.">
          Every opportunity weight from 0% (today&apos;s volume list) to 100% (pure opportunity), scored
          on the same {fr?.n_budget?.toLocaleString() ?? "–"}-prescriber budget. The dashed curve is
          the 2022→23 market where a weight would be chosen; the solid one is the 2023→24 holdout.
          Drag the slider; hover any point.
        </SectionHead>
        {q.isPending || !d ? <SkeletonChart h={420} /> : (
          <FrontierChart rows={d.frontier} floor={fr?.abs_floor_vs_volume ?? 0.9}
            tuned={fr?.selected_weight ?? null} />
        )}
        {fr && (
          <div className="mt-6 grid gap-3 md:grid-cols-3">
            <Finding tone="var(--neg)" k="Tuned on 2022→23"
              v={`${pct(fr.selected_weight, 0)} weight → keeps ${pct(fr.holdout_abs_vs_volume)} in 2024`}
              s={`clears the floor in ${pct(fr.holdout_p_clears_floor, 0)} of re-draws`} />
            <Finding tone="var(--pos)" k="Equal weight (recommended)"
              v={`${mult(fr.equal_weight_share_vs_volume)} share · ${pct(fr.equal_weight_abs_vs_volume)} kept`}
              s={`clears the floor in ${pct(fr.equal_weight_p_clears_floor, 0)} of re-draws`} />
            <Finding tone="var(--warn)" k="If you need 95% confidence"
              v={`${pct(fr.robust_weight_p95, 0)} weight · ${mult(robust?.share_vs_volume)} share`}
              s={`gives up ${(((fr.equal_weight_share_vs_volume ?? 0) - (robust?.share_vs_volume ?? 0)) * 100).toFixed(1)} points of share gain for the margin`} />
          </div>
        )}
        <Caveat>
          <strong>So what.</strong> The frontier&apos;s shape is stable but it shifts a couple of points
          a year, so a weight set to sit exactly on the floor is a coin toss next year. Keep 50/50, which
          had a {eqSel ? ((eqSel.abs_vs_volume - floor) * 100).toFixed(1) : "–"}-point margin when it would have been set, and re-read the
          floor at every annual refresh. Move to {pct(fr?.robust_weight_p95, 0)} if the brand team would
          rather give up a little share gain than risk the base.
        </Caveat>
      </Reveal>

      {/* ---- Q2 ---------------------------------------------------------- */}
      <Reveal as="section" className="card mb-8 p-6 sm:p-8">
        <SectionHead eyebrow="Q2 · Headcount" kind="SCENARIO"
          title="Headcount turns on one number public data cannot supply. Here is the dial.">
          Marginal ROI of the last rep at every force size, for the call response and net price you
          choose. Today&apos;s 60 reps pay for themselves only if a year of calls captures{" "}
          {pct(d?.headline.required_ceiling_at_current, 2)} of a prescriber&apos;s remaining opportunity.
        </SectionHead>
        {q.isPending || !d ? <SkeletonChart h={380} /> : <HeadcountExplorer data={d} />}
        <Caveat>
          <strong>Critical point: the price is falling.</strong> CMS&apos;s negotiated 2026 Medicare
          price for a 30-day supply is {usd(d?.economics.ira_2026_price_per_fill)} against the{" "}
          {usd(d?.economics.net_revenue_per_30day_fill.base)} net assumed here. That does not touch
          the re-targeting recommendation, which costs nothing, but it raises the bar for every
          additional Medicare rep by{" "}
          {d ? mult(d.economics.net_revenue_per_30day_fill.base / d.economics.ira_2026_price_per_fill, 2) : "–"}.
          Hiring ahead of a measured response would be buying into a shrinking margin.
        </Caveat>
      </Reveal>

      {/* ---- Q3 ---------------------------------------------------------- */}
      <Reveal as="section" className="card p-6 sm:p-8">
        <SectionHead eyebrow="Q3 · Pilot design" kind="SCENARIO"
          title="The endpoint decides whether the pilot works. Score it on share points, not fills.">
          The pilot has to detect the break-even response: anything weaker means the force is
          over-sized whatever the targeting. Toggle the endpoint and watch the curve: branded fills
          are dominated by practice size, share points are not.
        </SectionHead>
        {q.isPending || !d ? <SkeletonChart h={360} /> : <PilotPower pilot={d.pilot} />}
        {sh && fi && (
          <div className="mt-6 grid gap-3 md:grid-cols-3">
            <Finding tone="var(--pos)" k="Share points, 20% hold-out"
              v={`${pct(sh.power_holdout20_6m, 0)} power at 6 months`}
              s={`signal-to-noise ${(sh.effect_per_year / sh.sd_per_year).toFixed(3)} per year`} />
            <Finding tone="var(--neg)" k="Branded fills, same design"
              v={`${pct(fi.power_holdout20_6m, 0)} power at 6 months`}
              s={`signal-to-noise ${(fi.effect_per_year / fi.sd_per_year).toFixed(3)}: 3× worse`} />
            <Finding tone="var(--warn)" k="Territory split, 30 v 30"
              v={`${pct(sh.power_territory_split_6m, 0)} power at 6 months`}
              s="cleaner for reps, no prescriber is denied calls" />
          </div>
        )}
        <Caveat>
          <strong>Recommended design.</strong> Randomly hold out 20% of the new list for two quarters
          (no calls, everything else unchanged), score both arms on brand-share change with a
          prior-year adjustment, and read it at month six. If the effect is below half of break-even,
          the force is larger than calling justifies; if it is above twice break-even, the headcount
          case reopens with a measured number. Absolute fills stay as a guardrail, not the endpoint.
        </Caveat>
      </Reveal>

      {/* ---- Q4 ---------------------------------------------------------- */}
      <Reveal as="section" className="card mt-8 p-6 sm:p-8">
        <SectionHead eyebrow="Q4 · Business case" kind="SCENARIO"
          title="Nobody knows what a call is worth. The pilot is the best bet for any belief a sceptic and a believer can both hold.">
          Expected two-year value of each headcount strategy against your belief about how well calls
          work. Growing pays only if you are confident calls work at least{" "}
          {bc?.grow_pays_above_x != null ? `${bc.grow_pays_above_x}×` : "–"} as well as break-even (hiring,
          ramp-up and severance are priced in). Drag your own belief.
        </SectionHead>
        {q.isPending || !d ? <SkeletonChart h={400} /> : <BeliefExplorer data={d} />}

        {bc && (
          <div className="mt-8 grid gap-6 xl:grid-cols-[1.4fr_1fr]">
            <div>
              <p className="eyebrow mb-2">Payoff and regret over {bc.horizon_years} years, by the true response</p>
              <PayoffMatrix bc={bc} />
              <p className="mt-2 text-micro text-ink-faint normal-case tracking-normal">
                Regret is how much better the best decision would have done, had you known the true
                response. Hold + pilot has the smallest worst case of any option: it is the robust
                choice, not just the expected-value choice.
              </p>
            </div>
            <div className="slab p-6">
              <p className="eyebrow" style={{ color: "var(--mauve)" }}>The value stack</p>
              <ul className="mt-4 space-y-4">
                <Stack v={`${usd(rt?.["1.0"])} / yr`} k="Re-targeting, zero incremental cost"
                  s={`${usd(rt?.["0.5"])}–${usd(rt?.["2.0"])} if calls work 0.5–2× break-even`} />
                <Stack v={usd(bc.base_pilot_value)} k={`Pilot then decide, vs holding blind (${bc.horizon_years} yrs)`}
                  s={`${usd(bc.base_net_value_of_pilot)} more than the best decision made without it; already net of ${usd(bc.base_pilot_cost)} forgone during the hold-out`} />
                <Stack v={usd(bc.base_evpi)} k="Ceiling: value of knowing the response exactly"
                  s="no study can be worth more than this" />
                <Stack v="$0" k="Incremental headcount or hiring spend" s="until the pilot reads out" />
              </ul>
              <p className="mt-5 text-micro normal-case tracking-normal" style={{ color: "var(--text-faint)" }}>
                Belief centred on break-even (log-sd {bc.prior_log_sd}). Hiring {usd(bc.rep_hire_cost)}/rep,{" "}
                {bc.rep_ramp_months}-month ramp, severance {usd(bc.rep_separation_cost)}/rep: public benchmarks, in
                config/economics.yaml.
              </p>
            </div>
          </div>
        )}
      </Reveal>
    </>
  );
}

function Stack({ v, k, s }: { v: string; k: string; s: string }) {
  return (
    <li className="border-b pb-3 last:border-0" style={{ borderColor: "rgba(248,238,234,.12)" }}>
      <div className="num text-[26px] font-semibold leading-none" style={{ color: "var(--terracotta-hi)" }}>{v}</div>
      <div className="mt-1 text-small font-semibold" style={{ color: "var(--text-hi)" }}>{k}</div>
      <div className="text-micro normal-case tracking-normal" style={{ color: "var(--text-mute)" }}>{s}</div>
    </li>
  );
}

function QCard({ n, q, a }: { n: string; q: string; a: string }) {
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2">
        <span className="num rounded-full px-2 py-0.5 text-[11px] font-semibold text-white" style={{ background: "var(--plum)" }}>{n}</span>
        <span className="font-display text-[17px] font-bold">{q}</span>
      </div>
      <p className="mt-2 text-small text-ink-mute">{a}</p>
    </div>
  );
}

function Finding({ tone, k, v, s }: { tone: string; k: string; v: string; s: string }) {
  return (
    <div className="rounded-xl border-l-4 p-4" style={{ borderColor: tone, background: "var(--rule-soft)" }}>
      <div className="eyebrow">{k}</div>
      <div className="num mt-1 text-[16px] font-semibold">{v}</div>
      <div className="mt-0.5 text-micro text-ink-mute normal-case tracking-normal">{s}</div>
    </div>
  );
}
