/**
 * Prescriber detail drawer.
 *
 * The opportunity breakdown here is the most important thing on the page: it
 * shows WHY a prescriber scored the way they did — what they currently give us,
 * versus what the frontier says a comparable prescriber reaches. A score with
 * no visible derivation is a black box, and a black box is not defensible in a
 * brand meeting.
 */

import { useEffect, useRef, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import type { ExplanationRow, ForecastRow } from "@/lib/types";
import { compact, fmt, pct, personName, usd } from "@/lib/format";
import { DecileChip } from "@/components/Primitives";
import { ErrorState, SkeletonText } from "@/components/States";

export function HcpDrawer({ npi, onClose }: { npi: number; onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: qk.hcp(npi),
    queryFn: () => api.hcp(npi),
  });

  // A modal dialog for keyboard users: focus moves in on open, Tab cycles
  // inside the panel instead of wandering the page behind the overlay, Escape
  // closes, and focus returns to the row that opened it.
  //
  // onClose is read through a ref: callers pass an inline arrow, and with it
  // in the deps the effect re-ran on every parent render and yanked focus
  // back to the panel mid-interaction.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
      if (e.key !== "Tab" || !panelRef.current) return;
      const items = panelRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (items.length === 0) return;
      const first = items[0]!, last = items[items.length - 1]!;
      const inside = panelRef.current.contains(document.activeElement);
      if (e.shiftKey && (document.activeElement === first || !inside)) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && (document.activeElement === last || !inside)) {
        e.preventDefault(); first.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    panelRef.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, []);

  const hcp = data?.hcp;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close detail"
        onClick={onClose}
        className="absolute inset-0 bg-black/25 backdrop-blur-[2px]"
      />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="Prescriber detail"
        tabIndex={-1}
        className="relative h-full w-full max-w-[480px] overflow-y-auto border-l
                   border-rule bg-panel p-6 outline-none"
        style={{ animation: "drawer-in 260ms cubic-bezier(0.16,1,0.3,1)" }}
      >
        <style>{`@keyframes drawer-in{from{transform:translateX(24px);opacity:0}to{transform:none;opacity:1}}`}</style>

        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <p className="eyebrow mb-1">Prescriber</p>
            {isPending ? (
              <SkeletonText lines={2} />
            ) : (
              <>
                <h2 className="text-h2">
                  {personName(hcp?.last_name, hcp?.first_name)}
                </h2>
                <p className="text-small text-ink-mute">
                  {hcp?.specialty ?? "––"} · {hcp?.city ?? "––"}, {hcp?.state ?? "––"}
                </p>
                <p className="num text-micro text-ink-faint mt-1 normal-case tracking-normal">
                  NPI {npi}
                  {data?.segment ? ` · ${data.segment}` : ""}
                </p>
              </>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-rule px-2 py-1 text-small transition-colors
                       duration-instant hover:border-signal hover:text-signal"
          >
            Close
          </button>
        </div>

        {isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isPending ? (
          <SkeletonText lines={8} />
        ) : (
          <>
            <OpportunityBreakdown
              actual={hcp?.brand_fills ?? 0}
              potentialBrand={hcp?.potential_brand ?? 0}
              opportunity={hcp?.opportunity ?? 0}
            />

            {data.forecast && <ForecastCard f={data.forecast} />}

            {data.explanation && data.explanation.length > 0 && (
              <Section title="Why this potential: top drivers">
                <Drivers rows={data.explanation} />
              </Section>
            )}

            {data.uplift && (
              <Section title="Promotion response (uplift model)">
                <Row label="Estimated share change if promoted">
                  <span style={{ color: data.uplift.cate >= 0 ? "var(--pos)" : "var(--neg)" }}>
                    {data.uplift.cate >= 0 ? "+" : ""}{(data.uplift.cate * 100).toFixed(2)} pts
                  </span>
                </Row>
                <Row label="Propensity to be visited">{pct(data.uplift.propensity, 0)}</Row>
                <p className="text-micro text-ink-faint mt-2 normal-case tracking-normal">
                  Doubly-robust uplift estimate, held-out fold. Observational: it shows where
                  promotion is associated with movement; the pilot would test it.
                </p>
              </Section>
            )}

            <Section title="Ranking">
              <Row label="Opportunity decile">
                <DecileChip decile={hcp?.opportunity_decile} kind="opportunity" />
              </Row>
              <Row label="Volume decile">
                <DecileChip decile={hcp?.volume_decile} kind="volume" />
              </Row>
              <Row label="Achievable share (peer 75th pct)">
                {pct(hcp?.achievable_share)}
              </Row>
              <Row label="Current brand share">{pct(hcp?.brand_share)}</Row>
              <Row label="Planned calls / month">{fmt(hcp?.calls_per_month, 2)}</Row>
            </Section>

            {data.trend.length > 0 && (
              <Section title="Three-year trend">
                <table className="w-full text-small">
                  <thead>
                    <tr className="border-b border-rule">
                      <th className="eyebrow py-1 text-left">Year</th>
                      <th className="eyebrow py-1 text-right">Class</th>
                      <th className="eyebrow py-1 text-right">Brand</th>
                      <th className="eyebrow py-1 text-right">Share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.trend.map((t) => (
                      <tr key={t.year} className="border-b border-rule-soft">
                        <td className="num py-1">{t.year}</td>
                        <td className="num py-1 text-right">{fmt(t.class_fills)}</td>
                        <td className="num py-1 text-right">{fmt(t.brand_fills)}</td>
                        <td className="num py-1 text-right">{pct(t.brand_share, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            )}

            {data.payments.length > 0 && (
              <Section title="Promotional payments">
                <table className="w-full text-small">
                  <thead>
                    <tr className="border-b border-rule">
                      <th className="eyebrow py-1 text-left">Year</th>
                      <th className="eyebrow py-1 text-right">Total</th>
                      <th className="eyebrow py-1 text-right">Focus brand</th>
                      <th className="eyebrow py-1 text-right">Mfrs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.payments.map((p) => (
                      <tr key={p.year} className="border-b border-rule-soft">
                        <td className="num py-1">{p.year}</td>
                        <td className="num py-1 text-right">{usd(p.pay_total)}</td>
                        <td className="num py-1 text-right">{usd(p.pay_focus)}</td>
                        <td className="num py-1 text-right">{fmt(p.n_manufacturers)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-micro text-ink-faint mt-2 normal-case tracking-normal">
                  Payments flow toward prescribers who are already high-volume. Presence
                  here is not evidence that promotion caused anything.
                </p>
              </Section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------- opportunity derivation */

function OpportunityBreakdown({ actual, potentialBrand, opportunity }: {
  actual: number;
  potentialBrand: number;
  opportunity: number;
}) {
  const total = Math.max(potentialBrand, actual, 1);
  const actualPct = (actual / total) * 100;
  const oppPct = (opportunity / total) * 100;

  return (
    <div className="card mb-5 p-4">
      <p className="eyebrow mb-2">Opportunity derivation</p>
      <div
        className="flex h-6 w-full overflow-hidden rounded-sm"
        role="img"
        aria-label={`Currently ${fmt(actual)} branded fills of a modelled ${fmt(potentialBrand)} achievable; ${fmt(opportunity)} untapped.`}
      >
        <div style={{ width: `${actualPct}%`, background: "var(--d9)" }} />
        <div style={{ width: `${oppPct}%`, background: "var(--d3)" }} />
      </div>
      <div className="mt-2 flex justify-between text-micro normal-case tracking-normal">
        <span className="text-ink-mute">
          <span className="num text-ink">{compact(actual)}</span> we have today
        </span>
        <span className="text-ink-mute">
          <span className="num text-ink">{compact(opportunity)}</span> untapped
        </span>
      </div>
      <p className="text-micro text-ink-faint mt-2 normal-case tracking-normal">
        Modelled achievable: <span className="num">{compact(potentialBrand)}</span> branded
        30-day fills — the τ=0.80 frontier for a comparable prescriber in a comparable market.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ atoms */

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-5">
      <h3 className="text-h3 mb-2">{title}</h3>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-rule-soft py-1.5 text-small">
      <span className="text-ink-mute">{label}</span>
      <span className="num">{children}</span>
    </div>
  );
}

/* -------------------------------------------------- forecast + drivers */

/** Two-part forecast: will they still write the brand, and how much if so. */
function ForecastCard({ f }: { f: ForecastRow }) {
  const max = Math.max(f.brand_fills_hi, 1) * 1.1;
  const x = (v: number) => `${(v / max) * 100}%`;
  return (
    <div className="mb-5 rounded-xl p-4" style={{ background: "color-mix(in oklab, var(--terracotta) 8%, transparent)" }}>
      <p className="eyebrow mb-2">{f.forecast_year} forecast · conformal 90%</p>
      <div className="flex items-baseline justify-between">
        <span className="num text-[24px] font-semibold">{fmt(f.brand_fills_pred)}</span>
        <span className="text-small text-ink-mute">
          branded fills if still writing · P(still writing) <strong className="num text-ink">{pct(f.p_active, 0)}</strong>
        </span>
      </div>
      <div className="relative mt-3 h-3 rounded-full" style={{ background: "var(--rule)" }}>
        <div className="absolute inset-y-0 rounded-full" style={{
          left: x(f.brand_fills_lo), width: `calc(${x(f.brand_fills_hi)} - ${x(f.brand_fills_lo)})`,
          background: "linear-gradient(90deg, var(--mauve), var(--terracotta))",
        }} />
        <div className="absolute -top-1 h-5 w-1 rounded" style={{ left: x(f.brand_fills_pred), background: "var(--plum)" }} />
      </div>
      <div className="num mt-1 flex justify-between text-micro text-ink-faint">
        <span>{fmt(f.brand_fills_lo)}</span><span>{fmt(f.brand_fills_hi)}</span>
      </div>
    </div>
  );
}

/** Exact TreeSHAP contributions from the frontier replica, as multipliers. */
function Drivers({ rows }: { rows: ExplanationRow[] }) {
  const max = Math.max(...rows.map((r) => Math.abs(r.contribution)), 0.01);
  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const up = r.contribution >= 0;
        return (
          <div key={r.rank} className="grid grid-cols-[1fr_120px_56px] items-center gap-2 text-small">
            <span className="min-w-0">
              <span className="block truncate">{r.label}</span>
              <span className="num block truncate text-micro text-ink-mute">{r.display ?? r.value}</span>
            </span>
            <span className="relative h-2 rounded-full" style={{ background: "var(--rule-soft)" }}>
              <span className="absolute inset-y-0 rounded-full" style={{
                left: up ? "50%" : `${50 - (Math.abs(r.contribution) / max) * 50}%`,
                width: `${(Math.abs(r.contribution) / max) * 50}%`,
                background: up ? "var(--terracotta)" : "var(--mauve)",
              }} />
              <span className="absolute inset-y-[-3px] left-1/2 w-px" style={{ background: "var(--ink-faint)" }} />
            </span>
            <span className="num text-right font-semibold" style={{ color: up ? "var(--terracotta-ink)" : "var(--ink-mute)" }}>
              ×{r.multiplier.toFixed(2)}
            </span>
          </div>
        );
      })}
      <p className="text-micro text-ink-faint normal-case tracking-normal">
        Each bar multiplies modelled potential against the average prescriber. Exact TreeSHAP
        from an XGBoost replica of the frontier (fidelity ρ 0.97).
      </p>
    </div>
  );
}
