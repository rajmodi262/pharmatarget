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
import { compact, fmt, pct, personName, usd } from "@/lib/format";
import { DecileChip } from "@/components/Primitives";
import { ErrorState, SkeletonText } from "@/components/States";

export function HcpDrawer({ npi, onClose }: { npi: number; onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: qk.hcp(npi),
    queryFn: () => api.hcp(npi),
  });

  // Escape closes; focus moves into the panel so keyboard users are not left
  // behind the overlay.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    panelRef.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

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
