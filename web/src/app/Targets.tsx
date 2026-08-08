/**
 * Targets -- the workhorse route, and the page that proves the tool works.
 *
 * THE LOAD-BEARING ARCHITECTURAL DECISION: filtering, sorting and pagination
 * all happen in SQL, server-side. The browser never holds more than one page.
 * Fetching 1.14M rows and filtering client-side is the single most common way
 * a data tool freezes during the demo it was built for.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";

import { api, qk, type HcpQuery } from "@/lib/api";
import { compact, fmt, personName, pct } from "@/lib/format";
import { useDebounced } from "@/lib/useDebounced";
import type { HcpRow } from "@/lib/types";
import { DecileChip, SectionHead, ShareBar } from "@/components/Primitives";
import { EmptyState, ErrorState, SkeletonTable } from "@/components/States";
import { HcpDrawer } from "./HcpDrawer";

const PAGE_SIZE = 200;
const ROW_HEIGHT = 34;

const SPECIALTIES = [
  "Cardiology", "Internal Medicine", "Primary Care", "Advanced Practice",
  "Hem/Onc", "Nephrology", "Neurology", "Other",
];

type SortKey =
  | "opportunity" | "class_fills" | "brand_share" | "calls_per_month"
  | "opportunity_decile" | "volume_decile" | "npi";

const COLUMNS: { key: keyof HcpRow; label: string; sortable?: SortKey; numeric?: boolean }[] = [
  { key: "npi", label: "NPI", sortable: "npi", numeric: true },
  { key: "last_name", label: "Name" },
  { key: "specialty_group", label: "Specialty" },
  { key: "state", label: "St" },
  { key: "class_fills", label: "Class fills", sortable: "class_fills", numeric: true },
  { key: "brand_share", label: "Brand share", sortable: "brand_share", numeric: true },
  { key: "opportunity", label: "Opportunity", sortable: "opportunity", numeric: true },
  { key: "opportunity_decile", label: "Opp", sortable: "opportunity_decile", numeric: true },
  { key: "volume_decile", label: "Vol", sortable: "volume_decile", numeric: true },
  { key: "calls_per_month", label: "Calls/mo", sortable: "calls_per_month", numeric: true },
];

export function Targets() {
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const [specialty, setSpecialty] = useState("");
  const [decileMin, setDecileMin] = useState(1);
  const [targetsOnly, setTargetsOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("opportunity");
  const [desc, setDesc] = useState(true);
  const [page, setPage] = useState(1);
  const [openNpi, setOpenNpi] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const debouncedQ = useDebounced(q, 250);

  // Fetch /api/meta to surface the data_scope disclosure when this
  // deployment serves a subset of the full analysed universe.
  const { data: meta } = useQuery({
    queryKey: qk.meta,
    queryFn: () => api.meta(),
    staleTime: Infinity, // meta never changes within a session
  });
  const dataScope = meta?.data_scope;

  const query: HcpQuery = {
    q: debouncedQ.trim() || undefined,
    state: state || undefined,
    specialty: specialty || undefined,
    decile_min: decileMin,
    decile_max: 10,
    targets_only: targetsOnly || undefined,
    sort,
    desc,
    page,
    page_size: PAGE_SIZE,
  };

  const { data, isPending, isError, error, refetch, isPlaceholderData } = useQuery({
    queryKey: qk.hcps(query),
    queryFn: () => api.hcps(query),
    placeholderData: keepPreviousData,
  });

  // Any filter change invalidates the current page number.
  useEffect(() => {
    setPage(1);
  }, [debouncedQ, state, specialty, decileMin, targetsOnly, sort, desc]);

  const onSort = useCallback((key: SortKey) => {
    setSort((prev) => {
      if (prev === key) {
        setDesc((d) => !d);
        return prev;
      }
      setDesc(true);
      return key;
    });
  }, []);

  const clearFilters = () => {
    setQ(""); setState(""); setSpecialty(""); setDecileMin(1); setTargetsOnly(false);
  };

  const onExport = () => {
    window.location.href = api.exportUrl({
      state: state || undefined,
      decile_min: decileMin,
      decile_max: 10,
      targets_only: targetsOnly || undefined,
    });
    setToast("Exported.");
    setTimeout(() => setToast(null), 2400);
  };

  return (
    <>
      <SectionHead eyebrow="Workhorse" title="Targets">
        Every prescriber, ranked on modelled opportunity. Filtering, sorting and
        pagination happen in SQL — the browser never holds the full table.
      </SectionHead>

      {/* Quiet scope disclosure: shown only in the deploy bundle, where the
          browsable list is capped at the top 50 000 prescribers by opportunity.
          The headline KPIs above (hcps_analysed: 1.38M) are computed on the
          full universe and remain correct; only this route's pager is limited.
          Visual weight matches the existing source-attribution lines. */}
      {dataScope?.mode === "deploy_bundle" && (
        <p className="text-micro text-ink-mute normal-case tracking-normal mb-4">
          Showing top {dataScope.prescribers_served.toLocaleString()} prescribers
          by opportunity (of {dataScope.prescribers_analysed.toLocaleString()}
          {" "}analysed). All headline figures reflect the full universe.{" "}
          <a href="/api/meta" target="_blank" rel="noopener"
             className="underline underline-offset-2 hover:text-ink">
            data_scope
          </a>
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[260px_1fr] lg:items-start">
        <FilterRail
          q={q} setQ={setQ}
          state={state} setState={setState}
          specialty={specialty} setSpecialty={setSpecialty}
          decileMin={decileMin} setDecileMin={setDecileMin}
          targetsOnly={targetsOnly} setTargetsOnly={setTargetsOnly}
          onExport={onExport}
          onClear={clearFilters}
          toast={toast}
        />

        <div className="card overflow-hidden">
          {/* Error is checked BEFORE pending. A query that has an error object
              must show it even if the status flag has not settled -- otherwise
              a failed request renders an infinite skeleton, which is the worst
              possible failure mode: it looks like the app is working. */}
          {isError || error ? (
            <div className="p-5">
              <ErrorState error={error} onRetry={() => void refetch()} />
            </div>
          ) : isPending ? (
            <SkeletonTable />
          ) : !data || data.rows.length === 0 ? (
            <EmptyState
              title="No prescribers match these filters."
              action={
                <button
                  type="button"
                  onClick={clearFilters}
                  className="rounded border border-rule px-3 py-1.5 text-small
                             transition-colors duration-instant hover:border-signal hover:text-signal"
                >
                  Lower the decile threshold or clear the state filter to widen the search
                </button>
              }
            />
          ) : (
            <>
              <VirtualTable
                rows={data.rows}
                sort={sort}
                desc={desc}
                onSort={onSort}
                onOpen={setOpenNpi}
                dimmed={isPlaceholderData}
              />
              <Pager
                page={data.page}
                pages={data.pages}
                total={data.total}
                onPrev={() => setPage((p) => Math.max(1, p - 1))}
                onNext={() => setPage((p) => Math.min(data.pages, p + 1))}
              />
            </>
          )}
        </div>
      </div>

      {openNpi !== null && (
        <HcpDrawer npi={openNpi} onClose={() => setOpenNpi(null)} />
      )}
    </>
  );
}

/* -------------------------------------------------------------- filter rail */

function FilterRail(props: {
  q: string; setQ: (v: string) => void;
  state: string; setState: (v: string) => void;
  specialty: string; setSpecialty: (v: string) => void;
  decileMin: number; setDecileMin: (v: number) => void;
  targetsOnly: boolean; setTargetsOnly: (v: boolean) => void;
  onExport: () => void;
  onClear: () => void;
  toast: string | null;
}) {
  const searchRef = useRef<HTMLInputElement>(null);

  // "/" focuses search -- the convention every dense tool shares.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const field = "w-full rounded-sm border border-rule bg-panel px-2 py-1.5 text-small text-ink";

  return (
    <aside className="card p-4 lg:sticky lg:top-6">
      <h3 className="text-h3 mb-3">Filters</h3>

      <label className="eyebrow mb-1 block" htmlFor="f-q">
        Search name or NPI
      </label>
      <input
        id="f-q" ref={searchRef} className={field} value={props.q}
        // Not trimmed here: trimming on every keystroke makes it impossible to
        // type a space, and surnames contain them. Trimmed at query time.
        onChange={(e) => props.setQ(e.target.value)}
        placeholder="PATEL  or  1457…"
        aria-describedby="f-q-hint"
      />
      <p id="f-q-hint" className="text-micro text-ink-faint mt-1 normal-case tracking-normal">
        Press <kbd className="num">/</kbd> to focus
      </p>

      <label className="eyebrow mb-1 mt-4 block" htmlFor="f-state">State</label>
      <input
        id="f-state" className={field} value={props.state} maxLength={2}
        onChange={(e) => props.setState(e.target.value.toUpperCase())}
        placeholder="TX"
      />

      <label className="eyebrow mb-1 mt-4 block" htmlFor="f-spec">Specialty</label>
      <select
        id="f-spec" className={field} value={props.specialty}
        onChange={(e) => props.setSpecialty(e.target.value)}
      >
        <option value="">All specialties</option>
        {SPECIALTIES.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>

      <label className="eyebrow mb-1 mt-4 block" htmlFor="f-dec">
        Opportunity decile ≥ <span className="num text-ink">{props.decileMin}</span>
      </label>
      <input
        id="f-dec" type="range" min={1} max={10} value={props.decileMin}
        onChange={(e) => props.setDecileMin(Number(e.target.value))}
        className="w-full accent-[var(--signal)]"
      />

      <label className="mt-4 flex items-center gap-2 text-small">
        <input
          type="checkbox" checked={props.targetsOnly}
          onChange={(e) => props.setTargetsOnly(e.target.checked)}
          className="accent-[var(--signal)]"
        />
        Targets only
      </label>

      <div className="mt-5 flex flex-col gap-2">
        <button
          type="button" onClick={props.onExport}
          className="rounded border border-rule px-3 py-1.5 text-small transition-colors
                     duration-instant hover:border-signal hover:text-signal"
        >
          Export current view
        </button>
        <button
          type="button" onClick={props.onClear}
          className="text-micro text-ink-mute normal-case tracking-normal underline-offset-2 hover:underline"
        >
          Clear all filters
        </button>
      </div>

      {/* The button names its action and keeps the name; the toast confirms. */}
      <div aria-live="polite" className="text-micro text-pos mt-2 h-4 normal-case tracking-normal">
        {props.toast}
      </div>
    </aside>
  );
}

/* ------------------------------------------------------------ virtual table */

function VirtualTable({ rows, sort, desc, onSort, onOpen, dimmed }: {
  rows: HcpRow[];
  sort: SortKey;
  desc: boolean;
  onSort: (k: SortKey) => void;
  onOpen: (npi: number) => void;
  dimmed: boolean;
}) {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
  });

  return (
    <div
      className="transition-opacity duration-quick"
      style={{ opacity: dimmed ? 0.55 : 1 }}
    >
      {/* Header is a separate grid from the virtual body so it can stay fixed
          while thousands of rows scroll beneath it. */}
      <div
        className="grid gap-0 border-b border-rule bg-panel px-3"
        style={{ gridTemplateColumns: GRID }}
      >
        {COLUMNS.map((c) => (
          <button
            key={String(c.key)}
            type="button"
            disabled={!c.sortable}
            onClick={() => c.sortable && onSort(c.sortable)}
            className={[
              "eyebrow py-2 text-left transition-colors duration-instant",
              c.numeric ? "text-right" : "",
              c.sortable ? "cursor-pointer hover:text-ink" : "cursor-default",
              c.sortable === sort ? "text-ink" : "",
            ].join(" ")}
            aria-sort={
              c.sortable === sort ? (desc ? "descending" : "ascending") : undefined
            }
          >
            {c.label}
            {c.sortable === sort && (desc ? " ↓" : " ↑")}
          </button>
        ))}
      </div>

      <div ref={parentRef} className="max-h-[62vh] overflow-auto">
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((v) => {
            const r = rows[v.index];
            if (!r) return null;
            return (
              <div
                key={r.npi}
                role="button"
                tabIndex={0}
                onClick={() => onOpen(r.npi)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onOpen(r.npi);
                  }
                }}
                className="absolute inset-x-0 grid cursor-pointer items-center gap-0 border-b
                           border-rule-soft px-3 text-small transition-colors duration-instant
                           hover:bg-rule-soft focus-visible:bg-rule-soft"
                style={{
                  gridTemplateColumns: GRID,
                  height: v.size,
                  transform: `translateY(${v.start}px)`,
                }}
              >
                <span className="num text-right">{r.npi}</span>
                <span className="truncate">{personName(r.last_name, r.first_name)}</span>
                <span className="truncate text-ink-mute">{r.specialty_group ?? "––"}</span>
                <span className="num">{r.state ?? "––"}</span>
                <span className="num text-right">{fmt(r.class_fills)}</span>
                <span className="flex items-center justify-end gap-1.5">
                  <span className="num text-micro">{pct(r.brand_share, 0)}</span>
                  <ShareBar value={r.brand_share} />
                </span>
                <span className="num text-right">{compact(r.opportunity)}</span>
                <span className="text-right">
                  <DecileChip decile={r.opportunity_decile} kind="opportunity" />
                </span>
                <span className="text-right">
                  <DecileChip decile={r.volume_decile} kind="volume" />
                </span>
                <span className="num text-right">{fmt(r.calls_per_month, 2)}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

const GRID =
  "104px minmax(120px,1.4fr) minmax(110px,1fr) 34px 90px 108px 92px 46px 46px 72px";

/* ------------------------------------------------------------------- pager */

function Pager({ page, pages, total, onPrev, onNext }: {
  page: number; pages: number; total: number;
  onPrev: () => void; onNext: () => void;
}) {
  const btn =
    "rounded border border-rule px-2.5 py-1 text-small transition-colors duration-instant " +
    "hover:border-signal hover:text-signal disabled:opacity-40 disabled:hover:border-rule " +
    "disabled:hover:text-ink disabled:cursor-not-allowed";
  return (
    <div className="flex items-center justify-between border-t border-rule px-4 py-3">
      <span className="text-micro text-ink-mute normal-case tracking-normal">
        <span className="num">{fmt(total)}</span> prescribers · page{" "}
        <span className="num">{page}</span> of <span className="num">{fmt(pages)}</span>
      </span>
      <div className="flex gap-2">
        <button type="button" className={btn} onClick={onPrev} disabled={page <= 1}>
          Previous
        </button>
        <button type="button" className={btn} onClick={onNext} disabled={page >= pages}>
          Next
        </button>
      </div>
    </div>
  );
}
