/**
 * Territories -- the before/after that carries the project.
 *
 * The map is an Albers-style scatter of ZIP3 centroids, sized by workload and
 * coloured by territory. Not a choropleth: CMS gives no polygons, and inventing
 * boundaries we do not have would be a fabrication dressed as precision. Points
 * are honest about what the data actually is.
 *
 * The rep slider snaps to pre-solved values. Solving on demand would take
 * minutes and time out exactly when someone is watching.
 */

import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { fmt, mult, pct, stat } from "@/lib/format";
import type { TerritorySummaryRow, TerritoryUnit } from "@/lib/types";
import { Kpi, SectionHead, SourceLine } from "@/components/Primitives";
import { ErrorState, SkeletonChart, SkeletonKpiRow } from "@/components/States";

type Alignment = "optimised" | "baseline";

export function Territories() {
  const [nReps, setNReps] = useState(60);
  const [alignment, setAlignment] = useState<Alignment>("optimised");

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: qk.territories(nReps, alignment),
    queryFn: () => api.territories(nReps, alignment),
    placeholderData: keepPreviousData,
  });

  const presolved = data?.presolved_rep_counts ?? [40, 50, 60, 70, 80];
  const stats = data?.stats?.[0];
  const head = data?.headline;

  return (
    <>
      <SectionHead eyebrow="Exhibit E5" title="Territory alignment">
        Capacity-constrained clustering with a contiguity repair step. Plain capacitated
        k-means leaves a rep in Ohio owning ZIP3s in Indiana — tidy on a map,
        unimplementable in the field.
      </SectionHead>

      {/* ---- controls --------------------------------------------------- */}
      <div className="card mb-4 flex flex-wrap items-end gap-6 p-4">
        <div>
          <label className="eyebrow mb-1 block" htmlFor="t-reps">
            Field force size — <span className="num text-ink">{nReps} reps</span>
          </label>
          <input
            id="t-reps"
            type="range"
            min={0}
            max={presolved.length - 1}
            value={Math.max(0, presolved.indexOf(nReps))}
            onChange={(e) => setNReps(presolved[Number(e.target.value)] ?? 60)}
            className="w-[220px] accent-[var(--signal)]"
            list="reps-ticks"
          />
          <datalist id="reps-ticks">
            {presolved.map((n) => <option key={n} value={presolved.indexOf(n)} label={String(n)} />)}
          </datalist>
          <p className="text-micro text-ink-faint mt-1 normal-case tracking-normal">
            Snaps to pre-solved sizes: {presolved.join(" · ")}
          </p>
        </div>

        <div>
          <span className="eyebrow mb-1 block">Alignment</span>
          <div className="flex gap-2">
            {(["baseline", "optimised"] as Alignment[]).map((a) => (
              <button
                key={a}
                type="button"
                onClick={() => setAlignment(a)}
                aria-pressed={alignment === a}
                className={[
                  "rounded border px-3 py-1.5 text-small transition-colors duration-instant",
                  alignment === a
                    ? "border-signal bg-signal text-white"
                    : "border-rule hover:border-signal hover:text-signal",
                ].join(" ")}
              >
                {a === "baseline" ? "Before — alphabetical" : "After — optimised"}
              </button>
            ))}
          </div>
        </div>
      </div>

      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : isPending ? (
        <>
          <SkeletonKpiRow />
          <div className="mt-4"><SkeletonChart h={340} /></div>
        </>
      ) : (
        <>
          <div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Kpi
              label="Workload imbalance"
              value={mult(stats?.imbalance_ratio, 2)}
              note="max ÷ min territory"
            />
            <Kpi
              label="Workload CV"
              value={stat(stats?.workload_cv)}
              note={`baseline ${stat(head?.cv_before)}`}
            />
            <Kpi
              label="Contiguity"
              value={pct(stats?.contiguity_rate, 0)}
              tone={(stats?.contiguity_rate ?? 0) >= 0.95 ? "pos" : "neg"}
              note="single-component territories"
            />
            <Kpi
              label="Mean travel"
              value={`${fmt(stats?.mean_weighted_distance_mi)} mi`}
              note={`baseline ${fmt(head?.travel_before)} mi`}
            />
          </div>

          <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
            <section className="card p-5">
              <h3 className="text-h3 mb-3">
                {alignment === "baseline"
                  ? "Before — territories drawn alphabetically by state"
                  : "After — capacity-constrained and contiguous"}
              </h3>
              <TerritoryMap units={data?.units ?? []} />
              <SourceLine>
                Each dot is a ZIP3, sized by monthly call workload and coloured by
                territory. Straight-line geography — no drive-time matrix, which is where
                coastal and mountain territories would differ most.
              </SourceLine>
            </section>

            <section className="card p-5">
              <h3 className="text-h3 mb-3">Workload per territory</h3>
              <WorkloadBars rows={data?.territories ?? []} />
            </section>
          </div>

          {alignment === "optimised" && (
            <p className="text-micro text-ink-faint mt-4 normal-case tracking-normal max-w-prose">
              ZIP3 units are indivisible and each is roughly 10% of a territory&apos;s
              workload, which bounds achievable CV near 0.15 against the ±10% business
              target. Real alignments split to ZIP5 to go finer — out of scope here and
              listed under limitations rather than hidden by loosening the threshold.
            </p>
          )}
        </>
      )}
    </>
  );
}

/* -------------------------------------------------------------------- map */

function TerritoryMap({ units }: { units: TerritoryUnit[] }) {
  const geo = useMemo(() => {
    if (units.length === 0) return null;
    const lats = units.map((u) => u.lat);
    const lons = units.map((u) => u.lon);
    return {
      minLat: Math.min(...lats), maxLat: Math.max(...lats),
      minLon: Math.min(...lons), maxLon: Math.max(...lons),
      maxLoad: Math.max(...units.map((u) => u.workload), 1),
    };
  }, [units]);

  if (!geo) return <p className="text-small text-ink-mute">No geography available.</p>;

  const W = 620, H = 380, P = 14;
  const x = (lon: number) =>
    P + ((lon - geo.minLon) / (geo.maxLon - geo.minLon || 1)) * (W - 2 * P);
  const y = (lat: number) =>
    H - P - ((lat - geo.minLat) / (geo.maxLat - geo.minLat || 1)) * (H - 2 * P);

  // Golden-angle hue stepping keeps adjacent territory indices visually far
  // apart, so neighbouring regions never read as one blob.
  const hue = (t: number) => `hsl(${(t * 137.508) % 360} 58% 55%)`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full rounded"
      style={{ background: "var(--rule-soft)" }}
      role="img"
      aria-label={`Map of ${units.length} ZIP3 units coloured by assigned territory.`}
    >
      {units.map((u) => (
        <circle
          key={u.unit}
          cx={x(u.lon)}
          cy={y(u.lat)}
          r={3 + Math.sqrt(Math.max(u.workload, 0) / geo.maxLoad) * 7}
          fill={hue(u.territory)}
          fillOpacity={0.82}
          stroke="var(--panel)"
          strokeWidth={0.6}
        >
          <title>
            {`ZIP3 ${u.unit}${u.state ? ` (${u.state})` : ""} — territory ${u.territory}, ${fmt(u.workload)} calls/mo, ${fmt(u.n_hcps)} prescribers`}
          </title>
        </circle>
      ))}
    </svg>
  );
}

/* ------------------------------------------------------------------- bars */

function WorkloadBars({ rows }: { rows: TerritorySummaryRow[] }) {
  if (rows.length === 0) return <p className="text-small text-ink-mute">No territories.</p>;

  const sorted = [...rows].sort((a, b) => b.workload - a.workload);
  const max = Math.max(...sorted.map((r) => r.workload), 1);
  const mean = sorted.reduce((a, r) => a + r.workload, 0) / sorted.length;

  return (
    <>
      <div className="max-h-[320px] overflow-y-auto pr-1">
        {sorted.map((t) => {
          // Bars outside mean ±10% render in the warning colour: the tolerance
          // band is the client's requirement, so breaching it must be visible
          // without reading a number.
          const off = Math.abs(t.workload - mean) / (mean || 1);
          return (
            <div key={t.territory} className="mb-[3px] flex items-center gap-2">
              <span className="num w-6 shrink-0 text-micro text-ink-faint">{t.territory}</span>
              <span className="relative h-2.5 flex-1 rounded-sm" style={{ background: "var(--rule-soft)" }}>
                <span
                  className="absolute inset-y-0 left-0 rounded-sm"
                  style={{
                    width: `${(t.workload / max) * 100}%`,
                    background: off > 0.1 ? "var(--neg)" : "var(--d7)",
                  }}
                />
              </span>
              <span className="num w-11 shrink-0 text-right text-micro">{fmt(t.workload)}</span>
            </div>
          );
        })}
      </div>
      <p className="text-micro text-ink-faint mt-2 normal-case tracking-normal">
        Mean <span className="num">{fmt(mean)}</span> calls/month. Bars in{" "}
        <span style={{ color: "var(--neg)" }}>orange</span> sit outside ±10% of it.
      </p>
    </>
  );
}
