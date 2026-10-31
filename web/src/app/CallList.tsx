/**
 * Call list -- the page a rep or first-line manager actually works from.
 *
 * Everything else in the tool argues for a strategy; this page executes it.
 * Pick a territory and get its prescribers in visit order, with calls per
 * month, one sentence of why, and the 2025 forecast range. Export to CSV for
 * the CRM, or print it for the car.
 *
 * The territory lives in the URL (?t=3), so a manager can send each rep a
 * link to their own list.
 */

import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { compact, fmt, personName, pct } from "@/lib/format";
import type { CallListOption, CallListRow } from "@/lib/types";
import { DecileChip, Kpi, SectionHead, SourceLine } from "@/components/Primitives";
import { EmptyState, ErrorState, SkeletonKpiRow, SkeletonTable } from "@/components/States";
import { HcpDrawer } from "./HcpDrawer";

export function CallList() {
  const [params, setParams] = useSearchParams();
  const raw = params.get("t");
  const territory = raw !== null && /^\d+$/.test(raw) ? Number(raw) : null;
  const targetsOnly = params.get("all") !== "1";
  const [openNpi, setOpenNpi] = useState<number | null>(null);

  const set = (t: number | null, all = !targetsOnly) => {
    const next = new URLSearchParams();
    if (t !== null) next.set("t", String(t));
    if (all) next.set("all", "1");
    setParams(next, { replace: true });
  };

  const { data, isPending, isError, error, refetch, isPlaceholderData } = useQuery({
    queryKey: qk.callList(territory, targetsOnly),
    queryFn: () => api.callList(territory, targetsOnly),
    placeholderData: keepPreviousData,
  });

  const head = data?.territory ?? null;
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const totalCalls = rows.reduce((a, r) => a + (r.calls_per_month ?? 0), 0);

  return (
    <>
      <SectionHead eyebrow="Field execution" title="Who to see this month, in what order, and why.">
        One territory at a time, in visit order: targets first, then by modelled opportunity.
        Each row carries the single biggest reason the model rates the prescriber, and a
        calibrated 2025 forecast range.
      </SectionHead>

      {/* ---- controls --------------------------------------------------- */}
      <div className="card no-print mb-4 flex flex-wrap items-end gap-x-6 gap-y-3 p-4">
        <div className="min-w-[240px] flex-1 sm:flex-none">
          <label className="eyebrow mb-1 block" htmlFor="cl-territory">Territory (60-rep alignment)</label>
          <select
            id="cl-territory"
            className="w-full rounded-sm border border-rule bg-panel px-2 py-1.5 text-small text-ink sm:w-[320px]"
            value={territory ?? ""}
            onChange={(e) => set(e.target.value === "" ? null : Number(e.target.value))}
          >
            <option value="">Choose a territory…</option>
            {(data?.options ?? []).map((o) => (
              <option key={o.territory} value={o.territory}>
                {`T${o.territory} · ${o.states} · ${fmt(o.n_targets)} targets`}
              </option>
            ))}
          </select>
        </div>

        <label className="flex items-center gap-2 text-small">
          <input
            type="checkbox"
            checked={!targetsOnly}
            onChange={(e) => set(territory, e.target.checked)}
            className="accent-[var(--signal)]"
          />
          Include non-targets
        </label>

        {territory !== null && rows.length > 0 && (
          <div className="flex gap-2 sm:ml-auto">
            <a
              href={api.callListCsvUrl(territory, targetsOnly)}
              download
              className="rounded border border-rule px-3 py-1.5 text-small no-underline transition-colors
                         duration-instant hover:border-signal hover:text-signal"
            >
              Export CSV
            </a>
            <button
              type="button"
              onClick={() => window.print()}
              className="rounded border border-rule px-3 py-1.5 text-small transition-colors
                         duration-instant hover:border-signal hover:text-signal"
            >
              Print
            </button>
          </div>
        )}
      </div>

      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <>
          <SkeletonKpiRow />
          <div className="mt-4"><SkeletonTable /></div>
        </>
      ) : territory === null ? (
        <TerritoryPicker options={data?.options ?? []} onPick={(t) => set(t)} />
      ) : !head ? (
        <EmptyState title={`Territory ${territory} does not exist in the 60-rep alignment.`} />
      ) : (
        <div style={{ opacity: isPlaceholderData ? 0.55 : 1 }} className="transition-opacity duration-quick">
          <h3 className="print-only text-h3 mb-2">
            Territory {head.territory} · {head.states} · call list
          </h3>
          <div className="mb-4 grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
            <Kpi label={targetsOnly ? "Targets" : "Prescribers"} value={fmt(rows.length)}
                 note={`of ${fmt(head.n_hcps)} prescribers in the territory`} />
            <Kpi label="Calls per month" value={fmt(totalCalls)} note="planned for this list" />
            <Kpi label="Opportunity" value={compact(head.opportunity)} note="modelled brand fills, territory" />
            <Kpi label="States" value={head.states} note={`${fmt(head.workload)} calls/mo workload`} />
          </div>

          {rows.length === 0 ? (
            <EmptyState
              title="No targets in this territory."
              action={
                <button type="button" onClick={() => set(territory, true)}
                  className="rounded border border-rule px-3 py-1.5 text-small hover:border-signal hover:text-signal">
                  Show every prescriber in the territory instead
                </button>
              }
            />
          ) : (
            <>
              <CallTable rows={rows} onOpen={setOpenNpi} />
              <CallCards rows={rows} onOpen={setOpenNpi} />
            </>
          )}
          <SourceLine>
            Priority: targets first, then modelled opportunity. "Why" is the largest TreeSHAP
            driver of potential for that prescriber. Forecast: 90% conformal range for 2025
            brand fills if they keep writing the brand, with the probability they do.
            The hosted demo serves the top 50,000 prescribers by opportunity.
          </SourceLine>
        </div>
      )}

      {openNpi !== null && <HcpDrawer npi={openNpi} onClose={() => setOpenNpi(null)} />}
    </>
  );
}

/* ------------------------------------------------------- territory picker */

function TerritoryPicker({ options, onPick }: {
  options: CallListOption[];
  onPick: (t: number) => void;
}) {
  const [sort, setSort] = useState<"territory" | "n_targets" | "opportunity">("opportunity");
  const sorted = useMemo(
    () => [...options].sort((a, b) => (sort === "territory" ? a.territory - b.territory : b[sort] - a[sort])),
    [options, sort],
  );
  if (options.length === 0) return <EmptyState title="No territories have been solved yet." />;

  return (
    <section className="card p-5">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-h3">Choose a territory</h3>
        <label className="text-small text-ink-mute">
          Sort by{" "}
          <select
            className="rounded-sm border border-rule bg-panel px-1.5 py-0.5 text-small text-ink"
            value={sort}
            onChange={(e) => setSort(e.target.value as typeof sort)}
          >
            <option value="opportunity">opportunity</option>
            <option value="n_targets">targets</option>
            <option value="territory">number</option>
          </select>
        </label>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {sorted.map((o) => (
          <li key={o.territory}>
            <button
              type="button"
              onClick={() => onPick(o.territory)}
              className="flex w-full items-baseline justify-between gap-3 rounded border border-rule px-3 py-2
                         text-left transition-colors duration-instant hover:border-signal focus-visible:border-signal"
            >
              <span className="min-w-0">
                <span className="num text-small font-medium">T{o.territory}</span>{" "}
                <span className="truncate text-small text-ink-mute">{o.states}</span>
              </span>
              <span className="num shrink-0 text-micro text-ink-mute">
                {fmt(o.n_targets)} targets · {compact(o.opportunity)}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/* ---------------------------------------------------------------- table */

function forecastText(r: CallListRow): string {
  if (r.forecast_lo === null || r.forecast_hi === null) return "––";
  return `${fmt(r.forecast_lo)}–${fmt(r.forecast_hi)}`;
}

function CallTable({ rows, onOpen }: { rows: CallListRow[]; onOpen: (npi: number) => void }) {
  return (
    <div className="card hidden overflow-x-auto md:block print:block">
      <table className="w-full border-collapse text-small">
        <caption className="sr-only">Call list in visit order</caption>
        <thead>
          <tr className="border-b border-rule text-left">
            <th scope="col" className="eyebrow px-3 py-2 text-right">#</th>
            <th scope="col" className="eyebrow px-3 py-2">Prescriber</th>
            <th scope="col" className="eyebrow px-3 py-2">Specialty</th>
            <th scope="col" className="eyebrow px-3 py-2 text-right">Calls/mo</th>
            <th scope="col" className="eyebrow px-3 py-2 text-right">Opp</th>
            <th scope="col" className="eyebrow px-3 py-2">Why</th>
            <th scope="col" className="eyebrow px-3 py-2 text-right">2025 fills (90%)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.npi} className="border-b border-rule-soft align-top hover:bg-rule-soft">
              <td className="num px-3 py-2 text-right text-ink-mute">{r.priority}</td>
              <td className="px-3 py-2">
                <button
                  type="button"
                  onClick={() => onOpen(r.npi)}
                  className="text-left font-medium underline-offset-2 hover:underline focus-visible:underline"
                >
                  {personName(r.last_name, r.first_name)}
                </button>
                <span className="block text-micro text-ink-mute normal-case tracking-normal">
                  {r.city ?? "––"}, {r.state ?? "––"} · NPI <span className="num">{r.npi}</span>
                </span>
              </td>
              <td className="px-3 py-2 text-ink-mute">{r.specialty_group ?? "––"}</td>
              <td className="num px-3 py-2 text-right">{fmt(r.calls_per_month, 1)}</td>
              <td className="px-3 py-2 text-right">
                <DecileChip decile={r.opportunity_decile} kind="opportunity" />
              </td>
              <td className="max-w-[340px] px-3 py-2">{r.why ?? <span className="text-ink-faint">––</span>}</td>
              <td className="num px-3 py-2 text-right">
                {forecastText(r)}
                {r.p_active !== null && (
                  <span className="block text-micro text-ink-mute normal-case tracking-normal">
                    {pct(r.p_active, 0)} still writing
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Phones get cards: a 7-column table is unreadable at 375px. */
function CallCards({ rows, onOpen }: { rows: CallListRow[]; onOpen: (npi: number) => void }) {
  return (
    <ol className="flex flex-col gap-2 md:hidden print:hidden" aria-label="Call list in visit order">
      {rows.map((r) => (
        <li key={r.npi}>
          <button
            type="button"
            onClick={() => onOpen(r.npi)}
            className="card block w-full p-3 text-left transition-colors duration-instant hover:border-signal"
          >
            <span className="flex items-baseline justify-between gap-2">
              <span className="min-w-0">
                <span className="num mr-1.5 text-ink-mute">{r.priority}.</span>
                <span className="font-medium">{personName(r.last_name, r.first_name)}</span>
              </span>
              <span className="num shrink-0 text-small">{fmt(r.calls_per_month, 1)} calls/mo</span>
            </span>
            <span className="mt-0.5 block text-micro text-ink-mute normal-case tracking-normal">
              {r.specialty_group ?? "––"} · {r.city ?? "––"}, {r.state ?? "––"}
            </span>
            {r.why && <span className="mt-1.5 block text-small">{r.why}</span>}
            <span className="mt-1 block text-micro text-ink-mute normal-case tracking-normal">
              2025 fills <span className="num">{forecastText(r)}</span>
              {r.p_active !== null && <> · {pct(r.p_active, 0)} still writing</>}
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}
