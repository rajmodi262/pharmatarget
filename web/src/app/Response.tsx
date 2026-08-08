/**
 * Promotional response.
 *
 * The finding on this page is NOT the elasticity. It is the GAP between the
 * naive estimate and the matched one — that gap is what selection buys the
 * manufacturer, and showing it is more persuasive than any single coefficient.
 *
 * If the parallel-trends test failed, this page says so in the warning colour
 * and reports the estimate as an association. That behaviour was pre-committed
 * in CHARTER.md before the model was fit, which is the only thing that makes it
 * credible rather than convenient.
 */

import { useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { fmt, stat } from "@/lib/format";
import { Caveat, SectionHead, SourceLine } from "@/components/Primitives";
import { ErrorState, SkeletonText } from "@/components/States";

export function ResponseRoute() {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: qk.response,
    queryFn: api.responseModule,
    retry: 1,
  });

  if (isError) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const naive = data?.naive_ols ?? {};
  const pre = data?.pretrend ?? {};
  const match = data?.matching ?? {};
  const did = data?.did ?? {};

  const trendsHold = pre["parallel_trends_holds"] === true;
  const num = (v: unknown) => (typeof v === "number" ? v : null);

  return (
    <>
      <SectionHead eyebrow="Module 4" title="Promotional response">
        Does manufacturer payment exposure associate with brand share? The interesting
        number here is not the estimate — it is the distance between the naive estimate
        and the matched one.
      </SectionHead>

      {isPending ? (
        <SkeletonText lines={10} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          <section className="card p-5">
            <h3 className="text-h3 mb-3">The selection gap</h3>
            <table className="w-full text-small">
              <tbody>
                <Row label="Naive OLS elasticity" value={stat(num(naive["elasticity"]), 4)} />
                <Row
                  label="95% CI"
                  value={`${stat(num(naive["ci_low"]), 4)} … ${stat(num(naive["ci_high"]), 4)}`}
                />
                <Row label="Matched DiD (share points)" value={stat(num(did["did_estimate"]), 4)} />
                <Row label="Matched pairs" value={fmt(num(match["n_pairs"]))} />
                <Row
                  label="Worst post-match SMD"
                  value={stat(num(match["worst_smd_after"]))}
                  tone={match["balanced"] === true ? "pos" : "neg"}
                />
              </tbody>
            </table>
            <SourceLine>
              The distance between the naive and matched estimates is what selection buys
              the manufacturer. It is the reason the naive number must never be quoted
              alone.
            </SourceLine>
          </section>

          <section className="card p-5">
            <h3 className="text-h3 mb-3">Parallel-trends test</h3>
            <table className="w-full text-small">
              <tbody>
                <Row label="Treated pre-period Δ share" value={stat(num(pre["treated_pre_delta"]), 4)} />
                <Row label="Control pre-period Δ share" value={stat(num(pre["control_pre_delta"]), 4)} />
                <Row label="Difference" value={stat(num(pre["difference"]), 4)} />
                <Row
                  label="p-value"
                  value={stat(num(pre["p_value"]), 4)}
                  tone={trendsHold ? "pos" : "neg"}
                />
              </tbody>
            </table>

            {trendsHold ? (
              <SourceLine>
                Pre-trends are statistically indistinguishable, so the
                difference-in-differences design is defensible — subject to the
                observational caveats below.
              </SourceLine>
            ) : (
              <Caveat>
                <strong>Pre-trend test failed.</strong> Treated and control prescribers
                were <em>already</em> diverging before any payment was received. The
                identifying assumption does not hold, so the estimate is reported as an{" "}
                <strong>association only</strong> and all causal language has been removed.
                This was the pre-committed response, written into the charter before the
                model was fit.
              </Caveat>
            )}

            <p className="text-micro text-ink-faint mt-3 normal-case tracking-normal">
              Interpretation:{" "}
              <span className="text-ink-mute">
                {typeof did["interpretation"] === "string" ? did["interpretation"] : "––"}
              </span>
            </p>
          </section>

          <section className="card p-5 xl:col-span-2">
            <h3 className="text-h3 mb-2">Why every estimate here is an upper bound</h3>
            <Caveat>{data?.caveat}</Caveat>
          </section>
        </div>
      )}
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
