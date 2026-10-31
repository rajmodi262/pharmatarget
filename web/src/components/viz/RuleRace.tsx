/**
 * The five-rule race: realised 2024 outcomes of each rule's 60-rep list.
 *
 * Switching the metric re-sorts the bars with an animated reorder, which makes
 * the trade-off visible without a sentence: the ML share model leaps to the
 * top on share and collapses to the bottom on fills, volume does the reverse,
 * and the hybrid is the only rule near the top of both.
 */

import { useState } from "react";

import { pct, signed } from "@/lib/format";
import { useInView } from "@/lib/motion";
import { Toggle } from "./core";

export interface RaceRow {
  rule: string;
  share_capture?: number | null;
  abs_capture?: number | null;
  net_brand_fill_growth?: number | null;
  median_base_class_fills?: number | null;
}

type Metric = "share_capture" | "abs_capture" | "net_brand_fill_growth";

const LABEL: Record<string, string> = {
  hybrid: "Hybrid 50/50 — recommended",
  opportunity: "Opportunity (frontier model)",
  volume: "Volume — today",
  ml_abs: "ML: predict fills",
  ml_share: "ML: predict share",
};

const COLOR: Record<string, string> = {
  hybrid: "var(--terracotta)",
  opportunity: "var(--d5)",
  volume: "var(--plum)",
  ml_abs: "var(--v5)",
  ml_share: "var(--mauve)",
};

export function RuleRace({ rows }: { rows: RaceRow[] }) {
  const [ref, inView] = useInView<HTMLDivElement>(0.3);
  const [metric, setMetric] = useState<Metric>("share_capture");
  if (rows.length === 0) return null;

  const val = (r: RaceRow) => Number(r[metric] ?? 0);
  const sorted = [...rows].sort((a, b) => val(b) - val(a));
  const rank = new Map(sorted.map((r, i) => [r.rule, i]));
  const max = Math.max(...rows.map(val), 1e-9);
  const ROW = 46;

  return (
    <div ref={ref}>
      <div className="mb-4">
        <Toggle label="Metric" value={metric} onChange={setMetric} options={[
          { value: "share_capture", label: "Share-growth captured" },
          { value: "abs_capture", label: "Absolute growth captured" },
          { value: "net_brand_fill_growth", label: "Net branded fills" },
        ]} />
      </div>
      <div className="relative" style={{ height: rows.length * ROW }}>
        {rows.map((r) => {
          const i = rank.get(r.rule) ?? 0;
          const w = inView ? Math.max(val(r) / max, 0.01) * 100 : 0;
          const rec = r.rule === "hybrid";
          return (
            <div key={r.rule} className="absolute inset-x-0 flex items-center gap-3"
              style={{ top: i * ROW, height: ROW - 8, transition: "top 700ms cubic-bezier(.65,0,.35,1)" }}>
              <div className="w-[190px] shrink-0 text-small" style={{ fontWeight: rec ? 700 : 500 }}>
                {LABEL[r.rule] ?? r.rule}
              </div>
              <div className="relative h-full flex-1 overflow-hidden rounded-lg" style={{ background: "var(--rule-soft)" }}>
                <div className="absolute inset-y-0 left-0 rounded-lg"
                  style={{
                    width: `${w}%`,
                    background: rec
                      ? "linear-gradient(90deg, var(--terracotta), var(--terracotta-hi))"
                      : COLOR[r.rule] ?? "var(--mauve)",
                    boxShadow: rec ? "0 6px 20px -6px rgba(199,90,58,.7)" : undefined,
                    transition: "width 900ms cubic-bezier(.16,1,.3,1)",
                  }} />
                <span className="num absolute inset-y-0 right-3 flex items-center text-small font-semibold"
                  style={{ color: w > 88 ? "#fff" : undefined, transition: "color 300ms" }}>
                  {metric === "net_brand_fill_growth" ? signed(val(r)) : pct(val(r))}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
