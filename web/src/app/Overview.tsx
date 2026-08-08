/**
 * Overview -- answer first.
 *
 * The hero is a SENTENCE, not a chart. A reader who leaves after four seconds
 * should still have the recommendation. Charts are evidence for a claim already
 * made, never a puzzle to solve on the way to one.
 */

import { useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { compact, fmt, mult, pct, stat, usd } from "@/lib/format";
import { Caveat, EvidencePill, Kpi, SectionHead, SourceLine } from "@/components/Primitives";
import { ErrorState, SkeletonChart, SkeletonKpiRow, SyntheticBanner } from "@/components/States";
import { DisagreementMatrix, ReachCurve, RoiCurve, Tornado } from "@/components/charts/Charts";

export function Overview() {
  const summary = useQuery({ queryKey: qk.summary, queryFn: api.summary });
  const callplan = useQuery({ queryKey: qk.callplan, queryFn: api.callplan, retry: 1 });
  const sizing = useQuery({ queryKey: qk.sizing, queryFn: api.sizing, retry: 1 });

  if (summary.isError) {
    return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />;
  }

  const s = summary.data;
  const h1 = s?.headlines.h1;
  const h2 = s?.headlines.h2;
  const h3 = s?.headlines.h3;
  const dis = s?.disagreement;
  const terr = s?.territory;

  return (
    <>
      {s && <SyntheticBanner mode={s.data_mode} />}

      {/* ---- the hero claim ------------------------------------------- */}
      <div className="mb-8">
        <div className="mb-2 flex items-center gap-2">
          <span className="eyebrow">Recommendation</span>
          <EvidencePill kind="ARITHMETIC" />
        </div>
        {summary.isPending ? (
          <div className="skeleton h-24 w-full max-w-2xl" />
        ) : (
          <>
            <p className="text-claim font-display max-w-[30ch] leading-tight">
              Targeting on modelled opportunity instead of prescription volume reaches{" "}
              <span className="num font-semibold text-signal">
                {pct(h2?.opportunity_reach)}
              </span>{" "}
              of addressable opportunity on the same call budget, against{" "}
              <span className="num font-semibold text-signal">
                {pct(h2?.volume_reach)}
              </span>{" "}
              today.
            </p>
            <p className="text-small text-ink-mute mt-3 max-w-prose">
              The two rankings disagree for{" "}
              <span className="num">{pct(dis?.disagree_by_2plus_pct)}</span> of prescribers.
              That disagreement is the entire argument: a high-volume prescriber already at
              90% brand share has no headroom, and volume ranking cannot see it.
            </p>
          </>
        )}
      </div>

      {/* ---- KPI row --------------------------------------------------- */}
      {summary.isPending ? (
        <SkeletonKpiRow />
      ) : (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi
            label="Prescribers analysed"
            value={compact(s?.kpis.hcps_analysed)}
            note="Medicare Part D, three years"
          />
          <Kpi
            label="Targeted"
            value={compact(s?.kpis.hcps_targeted)}
            note={`${pct(s?.kpis.pct_targeted)} of the addressable market`}
          />
          <Kpi
            label="Monthly calls"
            value={compact(s?.kpis.monthly_calls)}
            note={`implies ${fmt(s?.kpis.implied_reps, 0)} reps vs ${fmt(s?.kpis.current_reps)} today`}
          />
          <Kpi
            label="Workload imbalance"
            value={`${mult(terr?.imbalance_before, 1)} → ${mult(terr?.imbalance_after, 1)}`}
            tone="pos"
            note={`contiguity ${pct(terr?.contiguity_before, 0)} → ${pct(terr?.contiguity_after, 0)}`}
          />
        </div>
      )}

      {/* ---- E1 + E3 --------------------------------------------------- */}
      <div className="mb-4 grid gap-4 xl:grid-cols-2">
        <section className="card p-5">
          <SectionHead
            eyebrow="Exhibit E1"
            kind="ARITHMETIC"
            title={`Volume and opportunity rankings disagree for ${pct(dis?.disagree_by_2plus_pct)} of prescribers`}
          />
          {callplan.isPending ? (
            <SkeletonChart h={260} />
          ) : callplan.isError ? (
            <ErrorState error={callplan.error} onRetry={() => void callplan.refetch()} />
          ) : (
            <>
              <DisagreementMatrix cells={callplan.data?.disagreement_matrix ?? []} />
              <div className="mt-3 flex gap-6 text-small">
                <span>
                  <span className="num font-semibold" style={{ color: "var(--pos)" }}>
                    {fmt(dis?.volume_low_opportunity_high)}
                  </span>{" "}
                  <span className="text-ink-mute">skipped by the volume rule</span>
                </span>
                <span>
                  <span className="num font-semibold" style={{ color: "var(--neg)" }}>
                    {fmt(dis?.volume_high_opportunity_low)}
                  </span>{" "}
                  <span className="text-ink-mute">over-served by it</span>
                </span>
              </div>
            </>
          )}
        </section>

        <section className="card p-5">
          <SectionHead
            eyebrow="Exhibit E3"
            kind="ARITHMETIC"
            title="Opportunity-weighted allocation reaches more on the same budget"
          />
          {callplan.isPending ? (
            <SkeletonChart h={220} />
          ) : (
            <>
              <ReachCurve points={callplan.data?.reach_curve ?? []} />
              <SourceLine>
                No behavioural assumption. Given a fixed number of calls, this is how much
                addressable opportunity each rule puts a rep in front of — not what
                happens next.
              </SourceLine>
            </>
          )}
        </section>
      </div>

      {/* ---- E4 + back-test -------------------------------------------- */}
      <div className="grid gap-4 xl:grid-cols-2">
        <section className="card p-5">
          <SectionHead
            eyebrow="Exhibit E4"
            kind="SCENARIO"
            title={`The marginal rep stops paying for itself at ${fmt(h3?.break_even_n_reps, 0)} reps, not ${fmt(h3?.current_n_reps)}`}
          />
          {sizing.isPending ? (
            <SkeletonChart h={220} />
          ) : sizing.isError ? (
            <ErrorState error={sizing.error} onRetry={() => void sizing.refetch()} />
          ) : (
            <>
              <RoiCurve
                points={sizing.data?.roi_curve ?? []}
                currentReps={h3?.current_n_reps ?? null}
              />
              <p className="text-small mt-2">
                At {fmt(h3?.current_n_reps)} reps the marginal rep returns{" "}
                <span className="num font-semibold">
                  ${stat(h3?.marginal_roi_at_current, 2)}
                </span>{" "}
                per $1. Incremental contribution to break-even:{" "}
                <span className="num font-semibold">{usd(h3?.incremental_profit)}</span>.
              </p>
              <div className="mt-4">
                <p className="eyebrow mb-2">Sensitivity</p>
                <Tornado rows={sizing.data?.tornado ?? []} />
              </div>
              <Caveat>
                <strong>Scenario, not a result.</strong> This rests on a fitted response
                curve, not on observed rep calls — CMS data contains none. Across the full
                assumption grid, break-even lands anywhere from{" "}
                <span className="num">{fmt(h3?.sensitivity_range?.[0], 0)}</span> to{" "}
                <span className="num">{fmt(h3?.sensitivity_range?.[1], 0)}</span> reps.
              </Caveat>
            </>
          )}
        </section>

        <section className="card p-5">
          <SectionHead
            eyebrow="Back-test"
            kind="BACK-TESTED"
            title="Held out a year the model never saw, then checked whether the ranking ranks"
          />
          <table className="w-full text-small">
            <tbody>
              <Row label="Spearman (decile, realised growth)" value={stat(h1?.decile_spearman)} />
              <Row label="Share-growth capture vs volume rule" value={mult(h1?.share_growth_ratio)} />
              <Row label="Absolute-growth capture vs volume rule" value={mult(h1?.absolute_growth_ratio)} />
              <Row
                label="Gate G3"
                value={h1?.gate_passed ? "passed" : "failed"}
                tone={h1?.gate_passed ? "pos" : "neg"}
              />
            </tbody>
          </table>

          {/*
            The unfavourable number sits in the SAME frame, at the same size, as
            the favourable one. Tucking it into a footnote is what makes a
            reviewer start hunting; showing it is what makes them stop.
          */}
          <Caveat>
            <strong>Volume wins on absolute growth, and that is expected.</strong> A
            prescriber writing 400 fills can gain 40 by moving four share points; one
            writing 40 cannot gain 40 whatever happens. Absolute growth scales with
            baseline volume, so ranking by volume is close to tautologically strong on
            that metric. Share-point growth is volume-neutral, and that is the criterion —
            chosen before the model was fit.
          </Caveat>
          <SourceLine>
            The back-test measures where growth <em>happened</em>, with no rep call data in
            the holdout. It cannot identify where a call would have <em>caused</em> growth.
            No CMS-only design can.
          </SourceLine>
        </section>
      </div>
    </>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "pos" | "neg" }) {
  const color = tone === "pos" ? "var(--pos)" : tone === "neg" ? "var(--neg)" : undefined;
  return (
    <tr className="border-b border-rule-soft">
      <td className="py-1.5 text-ink-mute">{label}</td>
      <td className="num py-1.5 text-right font-medium" style={{ color }}>{value}</td>
    </tr>
  );
}
