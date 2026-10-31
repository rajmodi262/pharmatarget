/**
 * Overview -- answer first.
 *
 * The hero is a SENTENCE, not a chart. A reader who leaves after four seconds
 * should still have the recommendation. Then the three decisions, each with
 * its evidence class, then the exhibits that carry them. Every number comes
 * from the API; nothing on this page is typed in.
 */

import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { compact, fmt, mult, pct, stat, usd } from "@/lib/format";
import { CountUp, Reveal } from "@/lib/motion";
import { Caveat, EvidencePill, SectionHead, SourceLine } from "@/components/Primitives";
import { ErrorState, SkeletonChart, SyntheticBanner } from "@/components/States";
import { MatrixViz } from "@/components/viz/MatrixViz";
import { ReachViz } from "@/components/viz/ReachViz";
import { RuleRace, type RaceRow } from "@/components/viz/RuleRace";

export function Overview() {
  const summary = useQuery({ queryKey: qk.summary, queryFn: api.summary });
  const callplan = useQuery({ queryKey: qk.callplan, queryFn: api.callplan, retry: 1 });
  const decision = useQuery({ queryKey: qk.decision, queryFn: api.decision, retry: 1 });

  if (summary.isError) {
    return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />;
  }

  const s = summary.data;
  const h1 = s?.headlines.h1;
  const h3 = s?.headlines.h3;
  const rec = s?.headlines.recommendation;
  const dis = s?.disagreement;
  const terr = s?.territory;
  const fr = decision.data?.frontier_summary;
  const pilot = decision.data?.pilot;
  const bc = decision.data?.business_case;
  const rt = bc?.retargeting_per_year_by_response;
  const race: RaceRow[] = Object.entries(s?.headlines.business_case?.rules ?? {})
    .map(([rule, o]) => ({ rule, ...o }));

  return (
    <>
      {s && <SyntheticBanner mode={s.data_mode} />}

      {/* ---- hero ------------------------------------------------------ */}
      <section className="slab relative mb-6 overflow-hidden px-6 py-10 sm:px-10 sm:py-14">
        <div aria-hidden className="blob absolute -right-24 -top-24 h-[380px] w-[380px] rounded-full opacity-60"
          style={{ background: "radial-gradient(circle, rgba(224,118,79,.55), transparent 65%)" }} />
        <div aria-hidden className="blob absolute -bottom-32 left-1/3 h-[340px] w-[340px] rounded-full opacity-50"
          style={{ background: "radial-gradient(circle, rgba(195,160,167,.45), transparent 65%)", animationDelay: "-6s" }} />

        <div className="relative grid gap-10 xl:grid-cols-[1.35fr_1fr] xl:items-end">
          <div>
            <div className="mb-4 flex items-center gap-2">
              <span className="eyebrow" style={{ color: "var(--mauve)" }}>The recommendation</span>
              <EvidencePill kind="BACK-TESTED" />
            </div>
            <h1 className="display text-[clamp(2.6rem,6.2vw,5.6rem)]">
              Target the <span style={{ color: "var(--terracotta-hi)" }}>gap</span>,
              <br />
              not the <span className="serif-i" style={{ color: "var(--mauve)" }}>volume.</span>
            </h1>
            {summary.isPending ? (
              <div className="skeleton mt-6 h-16 max-w-xl" />
            ) : (
              <p className="mt-6 max-w-[58ch] text-[17px] leading-relaxed" style={{ color: "var(--text)" }}>
                Keep the same {fmt(h3?.current_n_reps)} reps and redirect their calls to a{" "}
                <strong style={{ color: "var(--text-hi)" }}>50/50 blend of opportunity and volume</strong>.
                In a year the model never saw, that list won{" "}
                <strong className="num" style={{ color: "var(--terracotta-hi)" }}>{mult(rec?.share_vs_volume)}</strong>{" "}
                the share gains of today&apos;s volume list while keeping{" "}
                <strong className="num" style={{ color: "var(--terracotta-hi)" }}>{pct(rec?.abs_vs_volume, 0)}</strong>{" "}
                of its absolute growth. Hold headcount until a pilot measures what a call is worth.
              </p>
            )}
            <div className="mt-7 flex flex-wrap gap-3">
              <Link to="/app/lab" className="rounded-full px-5 py-2.5 text-small font-semibold no-underline transition-transform hover:scale-[1.03]"
                style={{ background: "var(--terracotta)", color: "#fff", boxShadow: "0 10px 30px -10px rgba(199,90,58,.8)" }}>
                Open the decision lab →
              </Link>
              <Link to="/app/case" className="rounded-full border px-5 py-2.5 text-small font-semibold no-underline transition-colors hover:bg-white/10"
                style={{ borderColor: "rgba(248,238,234,.3)", color: "var(--text-hi)" }}>
                Read the case
              </Link>
              <Link to="/brief" className="rounded-full border px-5 py-2.5 text-small font-semibold no-underline transition-colors hover:bg-white/10"
                style={{ borderColor: "rgba(248,238,234,.3)", color: "var(--text-hi)" }}>
                ▶ Present
              </Link>
              <a href="/api/download/onepager" className="self-center text-small font-semibold no-underline"
                style={{ color: "var(--mauve)" }}>
                One-page memo (PDF)
              </a>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <HeroStat label="Share-growth win vs volume"
              value={<CountUp value={rec?.share_vs_volume} format={(v) => mult(v)} />}
              note="held-out 2024, same budget" />
            <HeroStat label="Absolute growth kept"
              value={<CountUp value={rec?.abs_vs_volume} format={(v) => pct(v, 0)} />}
              note={`P(clears 90% floor) ${pct(fr?.equal_weight_p_clears_floor, 0)}`} />
            <HeroStat label="Workload imbalance"
              value={<><CountUp value={terr?.imbalance_before} format={(v) => mult(v, 0)} /> → <CountUp value={terr?.imbalance_after} format={(v) => mult(v, 1)} /></>}
              note="max ÷ min territory, after redraw" />
            <HeroStat label="Rankings disagree"
              value={<CountUp value={dis?.disagree_by_2plus_pct} format={(v) => pct(v, 0)} />}
              note="of prescribers, by 2+ deciles" />
          </div>
        </div>
      </section>

      {/* ---- ticker ---------------------------------------------------- */}
      <div className="mb-10 overflow-hidden rounded-full border border-rule bg-panel py-2" aria-hidden>
        <div className="marquee text-small text-ink-mute">
          {[0, 1].map((k) => (
            <div key={k} className="flex shrink-0 gap-10 pr-10">
              <Tick v={compact(s?.kpis.hcps_analysed)} t="prescriber-years analysed" />
              <Tick v={compact(s?.kpis.hcps_in_market)} t="anticoagulant writers" />
              <Tick v="~39 GB" t="public CMS + Open Payments data" />
              <Tick v={fmt(s?.kpis.hcps_targeted)} t="prescribers on the 60-rep list" />
              <Tick v={pct(h1?.matched_growth_ratio != null ? h1.matched_growth_ratio - 1 : null, 0)} t="faster growth vs matched controls" />
              <Tick v={pct(terr?.contiguity_after, 0)} t="contiguous territories" />
              <Tick v={pct(pilot?.share?.power_holdout20_6m, 0)} t="pilot power, share endpoint, 6 months" />
            </div>
          ))}
        </div>
      </div>

      {/* ---- three decisions ------------------------------------------- */}
      <div className="mb-3 flex items-end justify-between">
        <h2 className="display text-[clamp(1.8rem,3vw,2.6rem)]">Three decisions</h2>
        <span className="serif-i hidden text-[18px] text-ink-mute sm:block">for the brand lead, in order</span>
      </div>
      <div className="mb-12 grid gap-4 lg:grid-cols-3">
        <Decision n="01" verb="Do now" tone="var(--pos)" title="Re-target the calls"
          body={`Move the 60-rep list to the 50/50 blend. Same reps, same cost, ${mult(rec?.share_vs_volume)} the share gains; ${pct(rec?.abs_vs_volume, 0)} of absolute growth kept.`}
          kind="BACK-TESTED" to="/app/targets" link="See the list" />
        <Decision n="02" verb="Do now" tone="var(--pos)" title="Redraw the territories"
          body={`Workload imbalance ${mult(terr?.imbalance_before, 0)} → ${mult(terr?.imbalance_after, 1)}, travel ${pct(terr?.travel_reduction_pct, 0)} shorter, every territory contiguous.`}
          kind="ARITHMETIC" to="/app/territories" link="See the map" />
        <Decision n="03" verb="Test first" tone="var(--warn)" title="Hold 60 reps, pilot the rest"
          body={`Public data show no measurable call response. A 20% prescriber hold-out scored on share points detects the break-even response with ${pct(pilot?.share?.power_holdout20_6m, 0)} power in six months.`}
          kind="SCENARIO" to="/app/lab" link="Design the pilot" />
      </div>

      {/* ---- the money ------------------------------------------------- */}
      {bc && (
        <Reveal as="section" className="slab mb-12 grid gap-6 p-6 sm:p-8 lg:grid-cols-[1fr_1fr_1fr_auto] lg:items-end">
          <Money v={<><CountUp value={rt?.["1.0"]} format={(v) => usd(v)} /> /yr</>}
            k="Re-targeting, at zero incremental cost"
            s={`${usd(rt?.["0.5"])}–${usd(rt?.["2.0"])} if calls work 0.5–2× break-even`} />
          <Money v={<CountUp value={bc.base_pilot_value} format={(v) => usd(v)} />}
            k={`The pilot, vs deciding blind (${bc.horizon_years} yrs)`}
            s={`for ${usd(bc.base_pilot_cost)} of forgone contribution; lowest worst-case regret`} />
          <Money v={<CountUp value={bc.grow_pays_above_x} format={(v) => `≥ ${v.toFixed(2)}×`} />}
            k="Belief needed to justify hiring now"
            s="calls would have to beat break-even by this much; no public evidence does" />
          <Link to="/app/lab" className="self-center whitespace-nowrap rounded-full px-5 py-2.5 text-small font-semibold no-underline"
            style={{ background: "var(--terracotta)", color: "#fff" }}>
            Test your own belief →
          </Link>
        </Reveal>
      )}

      {/* ---- E1 + E3 --------------------------------------------------- */}
      <div className="mb-6 grid gap-6 xl:grid-cols-2">
        <Reveal as="section" className="card min-w-0 p-6">
          <SectionHead eyebrow="Exhibit E1" kind="ARITHMETIC"
            title={`Volume and opportunity disagree for ${pct(dis?.disagree_by_2plus_pct, 0)} of prescribers`}>
            Hover any cell. Terracotta cells are under-ranked by volume, mauve cells over-ranked.
          </SectionHead>
          {callplan.isPending ? <SkeletonChart h={380} />
            : callplan.isError ? <ErrorState error={callplan.error} onRetry={() => void callplan.refetch()} />
              : <MatrixViz cells={callplan.data?.disagreement_matrix ?? []} />}
        </Reveal>

        <Reveal as="section" className="card min-w-0 p-6" delay={120}>
          <SectionHead eyebrow="Exhibit E3" kind="ARITHMETIC"
            title="On the same budget, opportunity ranking puts reps in front of more of the gap">
            Scrub the chart. At the 60-rep budget, opportunity reaches {pct(s?.headlines.h2.opportunity_reach)} of
            addressable opportunity against {pct(s?.headlines.h2.volume_reach)} for volume.
          </SectionHead>
          {callplan.isPending ? <SkeletonChart h={320} />
            : <ReachViz points={callplan.data?.reach_curve ?? []} budget={s?.kpis.pct_targeted} />}
          <SourceLine>
            No behavioural assumption: this is who each rule puts a rep in front of, not what happens next.
          </SourceLine>
        </Reveal>
      </div>

      {/* ---- business case -------------------------------------------- */}
      <div className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
        <Reveal as="section" className="card min-w-0 p-6">
          <SectionHead eyebrow="The business case" kind="BACK-TESTED"
            title="Each pure rule wins one metric. Only the blend is near the top of both.">
            Realised 2024 growth on each rule&apos;s {fmt(s?.headlines.business_case?.n_budget)}-prescriber
            list. Switch the metric and watch the order change.
          </SectionHead>
          <RuleRace rows={race} />
          <Caveat>
            <strong>The ML share model is not a winner.</strong> It tops share capture by picking
            prescribers with a median of {fmt(race.find((r) => r.rule === "ml_share")?.median_base_class_fills, 0)} class
            fills: share moves easily on a tiny base and produces almost no volume. That is why the
            rule that picks the recommendation requires 90% of volume&apos;s absolute growth.
          </Caveat>
        </Reveal>

        <Reveal as="section" className="card min-w-0 p-6" delay={120}>
          <SectionHead eyebrow="Back-test" kind="BACK-TESTED"
            title="Held out a year the model never saw, then checked the ranking ranks" />
          <table className="w-full text-small">
            <tbody>
              <Row label="Flagged vs propensity-matched controls"
                value={`${mult(h1?.matched_growth_ratio)} · +${stat(h1?.matched_paired_difference, 1)} fills`} />
              <Row label="95% interval, paired difference"
                value={`[${stat(h1?.matched_ci?.[0], 1)}, ${stat(h1?.matched_ci?.[1], 1)}]`} />
              <Row label="Share-growth capture vs volume" value={withCi(h1?.share_growth_ratio_ci, h1?.share_growth_ratio)} />
              <Row label="Absolute-growth capture vs volume" value={withCi(h1?.absolute_growth_ratio_ci, h1?.absolute_growth_ratio)} />
              <Row label="Spearman, prescriber level" value={withCi(h1?.spearman_ci, null, 3)} />
              <Row label="Blend weight tuned on 2022→23"
                value={fr?.selected_weight != null ? `${pct(fr.selected_weight, 0)}: fails out of time` : "–"} tone="neg" />
              <Row label="Equal weight, P(clears floor)" value={pct(fr?.equal_weight_p_clears_floor, 0)} tone="pos" />
              <Row label="Gate G3" value={h1?.gate_passed ? "passed" : "failed"} tone={h1?.gate_passed ? "pos" : "neg"} />
            </tbody>
          </table>
          <Caveat>
            <strong>Where growth happened, not what caused it.</strong> The holdout has no rep call
            data, so it shows that the ranking finds growing prescribers. Only the pilot can show
            that calling them causes growth.
          </Caveat>
        </Reveal>
      </div>
    </>
  );
}

function HeroStat({ label, value, note }: { label: string; value: ReactNode; note: string }) {
  return (
    <div className="rounded-2xl p-4 backdrop-blur-sm transition-transform duration-base hover:-translate-y-1"
      style={{ background: "rgba(248,238,234,.07)", border: "1px solid rgba(248,238,234,.12)" }}>
      <div className="eyebrow !text-[9.5px]" style={{ color: "var(--mauve)" }}>{label}</div>
      <div className="num mt-2 text-[clamp(1.6rem,2.6vw,2.3rem)] font-semibold leading-none" style={{ color: "var(--text-hi)" }}>
        {value}
      </div>
      <div className="mt-2 text-[11px]" style={{ color: "var(--text-faint)" }}>{note}</div>
    </div>
  );
}

function Money({ v, k, s }: { v: ReactNode; k: string; s: string }) {
  return (
    <div>
      <div className="num text-[clamp(1.8rem,3vw,2.6rem)] font-semibold leading-none" style={{ color: "var(--terracotta-hi)" }}>{v}</div>
      <div className="mt-2 text-small font-semibold" style={{ color: "var(--text-hi)" }}>{k}</div>
      <div className="text-micro normal-case tracking-normal" style={{ color: "var(--text-mute)" }}>{s}</div>
    </div>
  );
}

function Tick({ v, t }: { v: string; t: string }) {
  return (
    <span className="flex items-center gap-2 whitespace-nowrap">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--terracotta)" }} />
      <span className="num font-semibold text-ink">{v}</span> {t}
    </span>
  );
}

function Decision({ n, verb, tone, title, body, kind, to, link }: {
  n: string; verb: string; tone: string; title: string; body: string;
  kind: "BACK-TESTED" | "ARITHMETIC" | "SCENARIO"; to: string; link: string;
}) {
  return (
    <Reveal className="card group relative overflow-hidden p-6 transition-shadow duration-base hover:shadow-[var(--shadow-2)]">
      <span aria-hidden className="display pointer-events-none absolute -right-2 -top-6 text-[110px] opacity-[0.07]">{n}</span>
      <div className="flex items-center gap-2">
        <span className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold text-white" style={{ background: tone }}>{verb}</span>
        <EvidencePill kind={kind} />
      </div>
      <h3 className="font-display mt-4 text-[24px] font-bold leading-tight">{title}</h3>
      <p className="mt-2 text-small text-ink-mute">{body}</p>
      <Link to={to} className="mt-4 inline-flex items-center gap-1 text-small font-semibold no-underline" style={{ color: "var(--terracotta)" }}>
        {link} <span className="transition-transform duration-quick group-hover:translate-x-1">→</span>
      </Link>
    </Reveal>
  );
}

/** "1.39× [1.37, 1.41]" from a [low, estimate, high] triple. */
function withCi(
  ci: [number, number, number] | null | undefined,
  fallback: number | null | undefined,
  digits = 2,
): string {
  if (!ci) return digits === 3 ? stat(fallback) : mult(fallback);
  const [lo, est, hi] = ci;
  const head = digits === 3 ? stat(est) : mult(est);
  return `${head} [${stat(lo, digits)}, ${stat(hi, digits)}]`;
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  const color = tone === "pos" ? "var(--pos)" : tone === "neg" ? "var(--neg)" : undefined;
  return (
    <tr className="border-b border-rule-soft">
      <td className="py-2 text-ink-mute">{label}</td>
      <td className="num py-2 text-right font-medium" style={{ color }}>{value}</td>
    </tr>
  );
}
