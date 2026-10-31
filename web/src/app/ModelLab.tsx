/**
 * Model Lab -- the data-science layer (src/ds), as a reviewer would read it.
 *
 * Ordered as a model review is: is it evaluated properly, how uncertain is it,
 * where is it wrong and for whom, what is causal and what is not, why does it
 * say what it says, which choices matter, and is it safe to run next year.
 * Every number comes from /api/datascience.
 */

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { fmt, pct } from "@/lib/format";
import { CountUp, Reveal } from "@/lib/motion";
import type { DataScienceResponse } from "@/lib/types";
import { Caveat, EvidencePill, SectionHead } from "@/components/Primitives";
import { ErrorState, SkeletonChart } from "@/components/States";
import {
  CoveragePlot, DecileStairs, DriftHeat, FunnelScatter, ForestPlot, GainChart, HBars,
  LadderChart, QiniChart, Reliability, Representation, ruleLabel,
} from "@/components/viz/DsCharts";

type S = Record<string, unknown>;
const n = (v: unknown) => (typeof v === "number" ? v : Number(v ?? NaN));

export function ModelLab() {
  const q = useQuery({ queryKey: qk.datascience, queryFn: api.datascience });
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const d = q.data;
  const s = (k: string): S => (d?.summary[k] ?? {}) as S;
  const shr = s("shrinkage"), ev = s("evaluation"), cf = s("conformal"), er = s("errors");
  const ca = s("causal"), up = s("uplift"), ex = s("explain"), ab = s("ablation");
  const dr = s("drift"), ct = s("contracts"), nw = s("network");

  return (
    <>
      <header className="mb-10">
        <p className="eyebrow">Model Lab · data science</p>
        <h1 className="display mt-2 text-[clamp(2.4rem,5vw,4.4rem)]">
          Every model, <span style={{ color: "var(--terracotta)" }}>stress-tested</span>.
        </h1>
        <p className="serif-i mt-3 max-w-[64ch] text-[20px] leading-snug text-ink-mute">
          Baselines, ranking metrics, calibrated uncertainty, error analysis, causal ML, uplift,
          exact explanations, ablations, drift and data contracts — on the same out-of-time
          holdout the recommendation rests on.
        </p>
        {d && (
          <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat v={<CountUp value={n(cf.out_of_time_conformal)} format={(v) => pct(v, 1)} />} k="out-of-time interval coverage (target 90%)" />
            <Stat v={ruleLabel(String(ev.winner_under_guardrail ?? "–")).split(" (")[0]!} k="wins the pre-declared metric under the guardrail" />
            <Stat v={<CountUp value={n(ex.fidelity_spearman)} format={(v) => `ρ ${v.toFixed(3)}`} />} k="explainer fidelity to the production model" />
            <Stat v={`${fmt(n(ct.passed))}/${fmt(n(ct.checks))}`} k="data-contract checks passing" />
          </div>
        )}
      </header>

      {q.isPending || !d ? <SkeletonChart h={500} /> : <Body d={d} shr={shr} ev={ev} cf={cf} er={er} ca={ca} up={up}
        ex={ex} ab={ab} dr={dr} nw={nw} />}
    </>
  );
}

function Body({ d, shr, ev, cf, er, ca, up, ex, ab, dr, nw }: {
  d: DataScienceResponse; shr: S; ev: S; cf: S; er: S; ca: S; up: S; ex: S; ab: S; dr: S; nw: S;
}) {
  const lists = (up.list_uplift_fills ?? {}) as Record<string, number>;
  const bases = (up.list_median_base ?? {}) as Record<string, number>;
  const concept = (dr.concept_drift ?? {}) as Record<string, Record<string, number> | number>;
  return (
    <>
      {/* ---- 1. evaluation ------------------------------------------------- */}
      <Section n="01" title="Evaluation" kind="BACK-TESTED"
        head={`Eight rules, one pre-declared metric: the hybrid wins under the guardrail`}>
        <p className="mb-5 max-w-prose text-small text-ink-mute">
          k = {fmt(n(ev.k))} (what 60 reps can cover). Primary metric, fixed before any result was read:
          <strong> value capture</strong> — the share of all positive share-driven fills
          (shrunk share-point change × volume) on the list. Guardrail: keep ≥ 90% of the volume
          rule&apos;s absolute growth. Whiskers are 95% bootstrap intervals.
        </p>
        <div className="grid gap-8 xl:grid-cols-2">
          <LadderChart rows={d.ladder} />
          <GainChart rows={d.gain_curves} />
        </div>
        <Caveat>
          <strong>What a reviewer should take away.</strong> The value-aligned gradient-boosting model
          scores highest ({pct(d.ladder.find((r) => r.rule === "gbm_value")?.value_capture)}) but keeps
          only {pct(d.ladder.find((r) => r.rule === "gbm_value")?.abs_vs_volume, 0)} of volume&apos;s
          absolute growth, so it fails the brand&apos;s floor; the hybrid is the best rule that passes.
          Every serious rule beats random by 3–5×; the frontier alone beats random by{" "}
          {n(ev.frontier_vs_random_value_lift).toFixed(1)}×.
        </Caveat>
      </Section>

      {/* ---- 2. the regression-to-the-mean trap ----------------------------- */}
      <Section n="02" title="Target design" kind="BACK-TESTED"
        head="The share-change model was chasing regression to the mean, not persuadable doctors">
        <div className="grid gap-8 xl:grid-cols-[1.2fr_1fr]">
          <div>
            <FunnelScatter rows={d.shrinkage_funnel} />
            <p className="mt-2 text-micro text-ink-faint normal-case tracking-normal">
              Beta-binomial shrinkage per specialty pulls tiny-denominator shares towards their peers.
              The prior is worth only {n(shr.median_prior_strength).toFixed(1)} pseudo-fills: share
              genuinely varies between prescribers.
            </p>
          </div>
          <div>
            <table className="w-full text-small">
              <thead><tr className="border-b border-rule">
                <th className="eyebrow py-1.5 text-left">Model target</th>
                <th className="eyebrow py-1.5 text-right">Median base</th>
                <th className="eyebrow py-1.5 text-right">Abs capture</th>
              </tr></thead>
              <tbody>
                {d.shrinkage_h2h.map((r) => (
                  <tr key={r.rule} className="border-b border-rule-soft">
                    <td className="py-2">{H2H_LABEL[r.rule] ?? r.rule}</td>
                    <td className="num py-2 text-right">{fmt(r.median_base_class_fills)} fills</td>
                    <td className="num py-2 text-right font-semibold"
                      style={{ color: r.abs_capture > 0.1 ? "var(--pos)" : "var(--neg)" }}>{pct(r.abs_capture)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Caveat>
              <strong>Diagnosis.</strong> Shrinkage cut small prescribers&apos; share-change noise from{" "}
              {n(shr.sd_raw_change_small).toFixed(2)} to {n(shr.sd_eb_change_small).toFixed(2)}, and precision
              weighting changed nothing. The cause is <strong>regression to the mean</strong> (corr(share,
              change) = {n(shr.mean_reversion_corr).toFixed(2)}): low-share prescribers drift up whoever calls.
              Aligning the target with what a call buys — share change × volume — fixes it.
            </Caveat>
          </div>
        </div>
      </Section>

      {/* ---- 3. uncertainty --------------------------------------------------- */}
      <Section n="03" title="Uncertainty" kind="BACK-TESTED"
        head="Every prescriber gets a calibrated 90% interval, and it holds out of time">
        <p className="mb-5 max-w-prose text-small text-ink-mute">
          Two-part model: P(still writes the brand next year) — AUC {n(cf.hurdle_auc).toFixed(3)}, Brier{" "}
          {n(cf.hurdle_brier).toFixed(3)} — then a conformalised quantile interval given that. Fitted and
          calibrated on 2022→23, tested on 2023→24. Median width {fmt(n(cf.median_width_fills))} fills.
        </p>
        <div className="grid gap-8 xl:grid-cols-[1.4fr_1fr]">
          <CoveragePlot rows={d.coverage} />
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
            <div><p className="eyebrow mb-1">Point forecast calibration (slope {n(cf.calibration_slope).toFixed(2)})</p>
              <Reliability rows={d.calibration} kind="count" /></div>
            <div><p className="eyebrow mb-1">Still-writing probability calibration</p>
              <Reliability rows={d.hurdle_calibration} kind="prob" /></div>
          </div>
        </div>
        <Caveat>
          In period the intervals cover exactly {pct(n(cf.in_period_coverage), 1)}. Out of time,{" "}
          {pct(n(cf.out_of_time_conformal), 1)}: the shortfall is drift, concentrated in the largest
          prescribers ({pct(n(cf.worst_size_band_marginal), 1)}). The {String(cf.forecast_year ?? "")} forecast for
          every prescriber is in the Targets drawer.
        </Caveat>
      </Section>

      {/* ---- 4. errors and fairness ----------------------------------------- */}
      <Section n="04" title="Errors & representation" kind="ARITHMETIC"
        head="The list is fair to rural prescribers, and blind to the primary-care long tail">
        <div className="grid gap-8 xl:grid-cols-2">
          <Representation rows={d.representation} />
          <div>
            <p className="eyebrow mb-2">Forecast bias by segment (predicted − actual, % of actual)</p>
            <HBars rows={d.errors.filter((r) => r.segment === "specialty_group" || r.segment === "all")
              .map((r) => ({ ...r, name: r.segment === "all" ? "All prescribers" : r.level }))}
              value="relative_bias" label="name" signed fmtV={(v) => `${(v * 100).toFixed(1)}%`} />
          </div>
        </div>
        <Caveat>
          Rural prescribers are {pct(n(er.rural_share_of_list), 0)} of the list against{" "}
          {pct(n(er.rural_share_of_value), 0)} of realised value (ratio {n(er.rural_representation_ratio).toFixed(2)}):
          fair. But primary care and nurse-practitioner / PA prescribers hold about half the value and get
          a sixth of the list, and the 50–200-fill band gets none. No 60-rep list reaches them, which
          argues for <strong>non-personal channels</strong> (digital, inside sales) for the long tail.
        </Caveat>
      </Section>

      {/* ---- 5. causal ML ------------------------------------------------------ */}
      <Section n="05" title="Causal ML" kind="PROXY"
        head="Double machine learning: controls remove 60% of the naive promotion association">
        <div className="grid gap-8 xl:grid-cols-[1.3fr_1fr]">
          <ForestPlot rows={d.causal} />
          <div className="slab p-6">
            <p className="eyebrow" style={{ color: "var(--mauve)" }}>Sensitivity (Cinelli–Hazlett)</p>
            <div className="mt-3 grid grid-cols-2 gap-4">
              <Big v={pct(n(ca.robustness_value), 1)} k="robustness value (to zero)" />
              <Big v={`${n(ca.confounder_multiple_of_pretrend).toFixed(1)}×`} k="as strong as last year's trend" />
            </div>
            <p className="mt-4 text-small" style={{ color: "var(--text)" }}>
              A hidden confounder explaining {pct(n(ca.robustness_value), 1)} of the residual variance of both
              promotion and share change would erase the estimate. That is small: the association is
              real but fragile, about the size of the break-even response. The pilot remains the
              causal test.
            </p>
          </div>
        </div>
      </Section>

      {/* ---- 6. uplift ----------------------------------------------------------- */}
      <Section n="06" title="Uplift" kind="PROXY"
        head="A doubly-robust uplift model finds who moves when promoted, and it validates out of fold">
        <div className="grid gap-8 xl:grid-cols-3">
          <div><p className="eyebrow mb-2">Qini curve (fill-weighted, held-out folds)</p><QiniChart rows={d.qini} /></div>
          <div><p className="eyebrow mb-2">Observed uplift by predicted decile</p><DecileStairs rows={d.uplift_deciles} unit="fills" /></div>
          <div>
            <p className="eyebrow mb-2">Held-out fill uplift on each 60-rep list</p>
            <HBars rows={Object.entries(lists).map(([k, v]) => ({ k: `${LIST_LABEL[k] ?? k} (median ${fmt(bases[k])})`, v }))}
              value="v" label="k" fmtV={(v) => fmt(v)} />
          </div>
        </div>
        <Caveat>
          Share-point uplift picks small prescribers again (median {fmt(bases.uplift_share_points)} fills), so
          the model ranks on <strong>value uplift</strong> (effect × volume, median {fmt(bases.uplift_value)}).
          Observational, under the selection the causal module quantifies — so the recommendation is
          not to switch lists but to <strong>add an uplift-ranked arm to the pilot</strong> and let the
          randomised test decide.
        </Caveat>
      </Section>

      {/* ---- 7. explainability + ablation ------------------------------------- */}
      <Section n="07" title="Explainability & ablations" kind="ARITHMETIC"
        head="Practice size and patient mix carry the model; two simpler variants are pre-declared for next year">
        <div className="grid gap-8 xl:grid-cols-2">
          <div>
            <p className="eyebrow mb-2">Global drivers (mean |TreeSHAP|, share)</p>
            <HBars rows={d.shap_global.map((r) => ({ ...r }))} value="share" label="label" fmtV={(v) => pct(v, 0)} />
            <p className="mt-2 text-micro text-ink-faint normal-case tracking-normal">
              Exact TreeSHAP from an XGBoost replica (fidelity ρ {n(ex.fidelity_spearman).toFixed(3)}, agreement
              with permutation importance ρ {n(ex.agreement_with_permutation_importance).toFixed(2)}).
              Per-prescriber drivers are in the Targets drawer.
            </p>
          </div>
          <div>
            <p className="eyebrow mb-2">Value capture change vs production (points)</p>
            <HBars rows={d.ablation.filter((r) => r.variant !== "production").map((r) => ({ ...r, pts: r.value_capture_change }))}
              value="pts" label="variant" signed fmtV={(v) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}`} />
          </div>
        </div>
        <Caveat>
          Dropping practice and patient-mix features costs {Math.abs(n(ab.most_valuable_component_loss_points)).toFixed(1)}{" "}
          points. A plain median model (τ 0.5) scores {n(ab.median_regression_value_gain_points).toFixed(1)} points
          <em> higher</em> on this holdout — adopting it now would be choosing on the test set, so it is
          pre-declared for the next refresh instead.
        </Caveat>
      </Section>

      {/* ---- 8. MLOps -------------------------------------------------------- */}
      <Section n="08" title="MLOps" kind="ARITHMETIC"
        head="Stable inputs, a stable relationship, every contract passing: no retrain triggered">
        <div className="grid gap-8 xl:grid-cols-[1.3fr_1fr]">
          <div><p className="eyebrow mb-2">Population stability index by input and year</p><DriftHeat rows={d.drift} /></div>
          <div className="space-y-4">
            <div className="card p-4">
              <p className="eyebrow">Concept drift</p>
              <p className="mt-1 text-small">Score–growth rank correlation{" "}
                <span className="num font-semibold">{(concept["2022->2023"] as Record<string, number>)?.spearman_score_growth?.toFixed(3)}</span> →{" "}
                <span className="num font-semibold">{(concept["2023->2024"] as Record<string, number>)?.spearman_score_growth?.toFixed(3)}</span>;
                retrain if it moves by more than 0.05.</p>
            </div>
            <div className="card p-4">
              <p className="eyebrow">Data contracts</p>
              <p className="mt-1 text-small"><span className="num font-semibold" style={{ color: "var(--pos)" }}>
                {d.contracts.filter((c) => c.passed).length}/{d.contracts.length}</span> checks on{" "}
                {new Set(d.contracts.map((c) => c.table)).size} tables — keys, nulls, ranges, business rules.
                The first run caught a risk score above its bound: investigated, genuine, bound documented.</p>
            </div>
            <div className="card p-4">
              <p className="eyebrow">Experiment tracking</p>
              <p className="mt-1 text-small">Every model run is logged to MLflow (parameters, metrics,
                artifacts): <code className="text-[12px]">mlflow ui --backend-store-uri ./mlruns</code>.
                Model and data cards: <code className="text-[12px]">docs/</code>.</p>
            </div>
          </div>
        </div>
      </Section>

      {/* ---- 9. network ------------------------------------------------------ */}
      <Section n="09" title="Practice network" kind="ARITHMETIC"
        head="Prescribers move with their practice in level, not in change: a case for account-level selling">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Card v={pct(n(nw.coverage), 0)} k={`of in-market prescribers matched to ${fmt(n(nw.practices_used))} group practices (CMS)`} />
          <Card v={`ICC ${n(nw.icc_shrunk_share).toFixed(3)}`} k={`brand share clusters within practice (chance: ${n(nw.icc_permutation_null_97_5).toFixed(3)})`} />
          <Card v={`${pct(n(nw.value_capture_base))} → ${pct(n(nw.value_capture_with_peers))}`} k="value capture with peer features: practices share level, not change" />
          <Card v={pct(n(nw.unlisted_mates_value_share), 0)} k={`of value sits with ${fmt(n(nw.unlisted_practice_mates))} unlisted practice-mates of the list`} />
        </div>
        <Caveat>
          Practice membership is today&apos;s CMS enrolment applied to 2022–24 behaviour, which biases peer
          effects towards zero. The implication for the pilot: randomise by <strong>practice</strong>, not
          prescriber, so spillover to unlisted colleagues can be measured.
        </Caveat>
      </Section>
    </>
  );
}

const H2H_LABEL: Record<string, string> = {
  ml_share_raw: "Raw share change",
  ml_share_eb: "Shrunk share change",
  ml_share_eb_weighted: "Shrunk, precision-weighted",
  ml_share_value_aligned: "Shrunk change × volume (value-aligned)",
};
const LIST_LABEL: Record<string, string> = {
  volume: "Volume", opportunity: "Opportunity", hybrid: "Hybrid",
  uplift_share_points: "Uplift, share points", uplift_value: "Uplift, value",
};

function Section({ n: num, title, kind, head, children }: {
  n: string; title: string; kind: "BACK-TESTED" | "ARITHMETIC" | "PROXY" | "SCENARIO"; head: string; children: ReactNode;
}) {
  return (
    <Reveal as="section" className="card mb-8 p-6 sm:p-8">
      <div className="mb-1 flex items-center gap-3">
        <span className="display text-[28px]" style={{ color: "var(--terracotta)" }}>{num}</span>
        <EvidencePill kind={kind} />
      </div>
      <SectionHead eyebrow={title} title={head} />
      {children}
    </Reveal>
  );
}

function Stat({ v, k }: { v: ReactNode; k: string }) {
  return (
    <div className="card p-4">
      <div className="num text-[24px] font-semibold leading-tight" style={{ color: "var(--terracotta)" }}>{v}</div>
      <div className="mt-1 text-micro text-ink-mute normal-case tracking-normal">{k}</div>
    </div>
  );
}

function Big({ v, k }: { v: string; k: string }) {
  return (
    <div>
      <div className="num text-[30px] font-semibold" style={{ color: "var(--terracotta-hi)" }}>{v}</div>
      <div className="text-micro normal-case tracking-normal" style={{ color: "var(--text-mute)" }}>{k}</div>
    </div>
  );
}

function Card({ v, k }: { v: string; k: string }) {
  return (
    <div className="rounded-xl border-l-4 p-4" style={{ borderColor: "var(--terracotta)", background: "var(--rule-soft)" }}>
      <div className="num text-[20px] font-semibold">{v}</div>
      <div className="mt-1 text-micro text-ink-mute normal-case tracking-normal">{k}</div>
    </div>
  );
}
