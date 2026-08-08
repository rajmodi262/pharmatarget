/**
 * Method -- cheap to build, disproportionately credible.
 *
 * Data provenance, measured quality statistics, gate outcomes, every economic
 * assumption with its range and basis, and the full limitations list. This is
 * the page that answers "how do I know any of this is true?", and the fact that
 * it exists at all is part of the answer.
 */

import { useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { fmt, humanise, pct, stat } from "@/lib/format";
import { SectionHead } from "@/components/Primitives";
import { ErrorState, SkeletonText, SyntheticBanner } from "@/components/States";

export function Method() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: qk.meta,
    queryFn: api.meta,
  });

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />;
  if (isPending || !data) return <SkeletonText lines={14} />;

  const pm = data.potential_model ?? {};
  const sfa = data.sfa_crosscheck ?? {};
  const shap = data.shap_top_driver ?? {};
  const op = data.open_payments_match ?? {};
  const supp =
    Object.entries(data.suppression ?? {}).find(([k]) => k.includes("ev"))?.[1] ?? {};

  return (
    <>
      <SyntheticBanner mode={data.data_mode} warning={data.data_mode_warning} />

      <SectionHead eyebrow="Method" title="How this was built, and where it breaks" />

      <div className="grid gap-4 xl:grid-cols-2">
        <section className="card p-5">
          <h3 className="text-h3 mb-3">Pipeline</h3>
          <table className="w-full text-small">
            <tbody>
              <Row label="Data mode" value={data.data_mode} />
              <Row label="Years" value={(data.years?.all ?? []).join(", ")} />
              <Row label="Hold-out year" value={String(data.years?.holdout ?? "––")} />
              <Row label="Volume metric" value={data.volume_metric} />
              <Row label="Frontier quantile τ" value={stat(pm["tau"], 2)} />
              <Row label="In-sample coverage" value={stat(pm["in_sample_coverage"])} />
              <Row label="SFA cross-check (Spearman)" value={stat(sfa["spearman"])} />
              <Row
                label="Top SHAP driver"
                value={`${shap.feature ?? "––"} (${pct(shap.share, 0)})`}
              />
            </tbody>
          </table>
          <p className="text-micro text-ink-faint mt-2 normal-case tracking-normal">
            τ = 0.80 is the achievable frontier, not the conditional mean. A corrected-OLS
            stochastic-frontier approximation ranks prescribers almost identically, so the
            choice of quantile GBM is a convenience rather than a load-bearing assumption.
          </p>
        </section>

        <section className="card p-5">
          <h3 className="text-h3 mb-3">Data quality, measured not assumed</h3>
          <table className="w-full text-small">
            <tbody>
              <Row
                label="NPI-years with suppressed rows"
                value={pct(supp["pct_npi_years_affected"])}
              />
              <Row
                label="Claim volume hidden by suppression"
                value={pct(supp["hidden_share_of_total"])}
              />
              <Row label="Open Payments NPI fill rate" value={pct(op["npi_fill_rate"])} />
              <Row label="Linked to prescriber universe" value={pct(op["link_rate"])} />
              <Row
                label="Unmapped manufacturer rows"
                value={fmt(op["unmapped_manufacturer_rows"])}
              />
            </tbody>
          </table>
          <p className="text-micro text-ink-faint mt-2 normal-case tracking-normal">
            CMS <strong>removes</strong> NPI×drug rows under 11 claims from the file — they
            are absent, not blank. Hidden volume is sized by reconciling provider-level
            totals against the sum of drug rows, then imputed under a truncated
            distribution. Three imputation modes run end to end.
          </p>
        </section>
      </div>

      <section className="card mt-4 p-5">
        <h3 className="text-h3 mb-3">Gates</h3>
        <table className="w-full text-small">
          <tbody>
            {Object.entries(data.gates ?? {})
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <tr key={k} className="border-b border-rule-soft align-top">
                  <td className="py-1.5 font-medium">{k.toUpperCase().replace("_", " ")}</td>
                  <td
                    className="num py-1.5 text-right"
                    style={{ color: v?.passed ? "var(--pos)" : "var(--neg)" }}
                  >
                    {v?.passed ? "passed" : "failed → pre-committed pivot"}
                  </td>
                  <td className="text-micro text-ink-faint py-1.5 pl-4 normal-case tracking-normal">
                    {v?.criterion}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </section>

      <section className="card mt-4 p-5">
        <h3 className="text-h3 mb-3">Economic assumptions</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-small">
            <thead>
              <tr className="border-b border-rule">
                <th className="eyebrow py-1 text-left">Assumption</th>
                <th className="eyebrow py-1 text-right">Low</th>
                <th className="eyebrow py-1 text-right">Base</th>
                <th className="eyebrow py-1 text-right">High</th>
                <th className="eyebrow py-1 pl-4 text-left">Basis</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.economic_assumptions ?? {})
                .filter(([k]) => k !== "sizing")
                .map(([k, v]) => (
                  <tr key={k} className="border-b border-rule-soft align-top">
                    <td className="py-1.5">{humanise(k)}</td>
                    <td className="num py-1.5 text-right">{fmt(v.low, 2)}</td>
                    <td className="num py-1.5 text-right font-semibold">{fmt(v.base, 2)}</td>
                    <td className="num py-1.5 text-right">{fmt(v.high, 2)}</td>
                    <td className="text-micro text-ink-faint max-w-[380px] py-1.5 pl-4 normal-case tracking-normal">
                      {v.basis}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
        <p className="text-micro text-ink-faint mt-2 normal-case tracking-normal">
          Public benchmarks, not the client&apos;s actuals. The tornado chart on Overview
          ranks these by their effect on break-even headcount.
        </p>
      </section>

      <section className="card mt-4 p-5">
        <h3 className="text-h3 mb-3">Limitations</h3>
        <ol className="text-small text-ink-mute max-w-prose list-decimal space-y-2 pl-5">
          {(data.limitations ?? []).map((l) => <li key={l}>{l}</li>)}
        </ol>
      </section>

      <section className="card mt-4 p-5">
        <h3 className="text-h3 mb-3">Sources</h3>
        <ul className="text-small list-disc space-y-1.5 pl-5">
          {(data.sources ?? []).map((s) => (
            <li key={s.url}>
              <a href={s.url} target="_blank" rel="noopener noreferrer">{s.name}</a>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <tr className="border-b border-rule-soft">
      <td className="py-1.5 text-ink-mute">{label}</td>
      <td className="num py-1.5 text-right font-medium">{value}</td>
    </tr>
  );
}
