/**
 * Small shared primitives: evidence pills, decile chips, KPI tiles, section
 * headers, share bars.
 *
 * The EvidencePill is the most consultant-signalling element in the product.
 * Every headline number carries one, so a reader always knows whether they are
 * looking at something computed, something validated, or something projected.
 */

import type { ReactNode } from "react";
import { onRampText, opportunityColor, volumeColor } from "@/lib/scales";
import type { EvidenceClass } from "@/lib/types";

/* ---------------------------------------------------------- evidence pill */

const PILL_STYLE: Record<EvidenceClass, { bg: string; fg: string; label: string; title: string }> = {
  "BACK-TESTED": {
    bg: "rgba(23,166,115,.13)", fg: "var(--pos)", label: "Back-tested",
    title: "Validated against a year the model never saw during fitting.",
  },
  ARITHMETIC: {
    bg: "rgba(37,99,235,.13)", fg: "var(--info)", label: "Arithmetic",
    title: "Computed directly from the data. Contains no behavioural assumption.",
  },
  SCENARIO: {
    bg: "rgba(180,83,9,.14)", fg: "var(--warn)", label: "Scenario",
    title: "Depends on a stated assumption. Sensitivity range is published.",
  },
  PROXY: {
    bg: "rgba(125,138,156,.16)", fg: "var(--ink-mute)", label: "Proxy",
    title: "A stand-in measure, used because the ideal measure is unavailable.",
  },
};

export function EvidencePill({ kind }: { kind: EvidenceClass }) {
  const s = PILL_STYLE[kind];
  return (
    <span
      title={s.title}
      className="inline-block rounded-sm px-1.5 py-0.5 text-micro font-semibold uppercase align-middle"
      style={{ background: s.bg, color: s.fg, letterSpacing: "0.06em" }}
    >
      {s.label}
    </span>
  );
}

/* ----------------------------------------------------------- decile chips */

/**
 * Two chips, two ramps, deliberately. Opportunity is chromatic; volume is grey.
 * Once a reader learns "darker blue = higher opportunity" on the table they
 * read the map with no legend, and the greyness of volume carries the argument
 * without a sentence being written.
 */
export function DecileChip({ decile, kind = "opportunity" }: {
  decile: number | null | undefined;
  kind?: "opportunity" | "volume";
}) {
  if (decile === null || decile === undefined) {
    return <span className="text-ink-faint">––</span>;
  }
  const bg = kind === "opportunity" ? opportunityColor(decile) : volumeColor(decile);
  const fg = kind === "opportunity" ? onRampText(decile) : decile >= 6 ? "#fff" : "var(--ink)";
  return (
    <span
      className="num inline-block min-w-[24px] rounded-sm px-1.5 py-px text-center text-micro font-semibold"
      style={{ background: bg, color: fg, letterSpacing: 0 }}
      title={`${kind === "opportunity" ? "Opportunity" : "Volume"} decile ${decile} of 10`}
    >
      {decile}
    </span>
  );
}

/* ---------------------------------------------------------------- KPI tile */

export function Kpi({ label, value, note, tone = "default" }: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
  tone?: "default" | "pos" | "neg";
}) {
  const color =
    tone === "pos" ? "var(--pos)" : tone === "neg" ? "var(--neg)" : "var(--ink)";
  return (
    <div className="card p-4">
      <div className="eyebrow mb-1.5">{label}</div>
      <div className="kpi-value text-[24px] font-semibold leading-none tracking-tight" style={{ color }}>
        {value}
      </div>
      {note && <div className="text-micro text-ink-mute mt-1.5 normal-case tracking-normal">{note}</div>}
    </div>
  );
}

/* ------------------------------------------------------------ section head */

/**
 * Eyebrow carries the exhibit number and the evidence class; the heading is a
 * full sentence stating the finding. Never a noun phrase -- "Decile analysis"
 * tells a reader nothing, "Volume and opportunity disagree for 41%" is the
 * whole point.
 */
export function SectionHead({ eyebrow, kind, title, children }: {
  eyebrow?: string;
  kind?: EvidenceClass;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="mb-4">
      {(eyebrow || kind) && (
        <div className="mb-1.5 flex items-center gap-2">
          {eyebrow && <span className="eyebrow">{eyebrow}</span>}
          {kind && <EvidencePill kind={kind} />}
        </div>
      )}
      <h2 className="text-h2">{title}</h2>
      {children && (
        <p className="text-small text-ink-mute mt-1.5 max-w-prose">{children}</p>
      )}
    </header>
  );
}

/* -------------------------------------------------------------- share bar */

export function ShareBar({ value }: { value: number | null | undefined }) {
  const v = value === null || value === undefined || !Number.isFinite(value) ? 0 : value;
  return (
    <span
      className="relative inline-block h-[5px] w-11 overflow-hidden rounded-sm align-middle"
      style={{ background: "var(--d2)" }}
      aria-hidden="true"
    >
      <span
        className="absolute inset-y-0 left-0 rounded-sm"
        style={{ width: `${Math.min(100, Math.max(0, v * 100))}%`, background: "var(--d7)" }}
      />
    </span>
  );
}

/* -------------------------------------------------------------- caveat box */

/**
 * Styled, never hidden. The limitations of an analysis are a credibility asset
 * and belong in the same visual frame as the claim they qualify.
 */
export function Caveat({ children }: { children: ReactNode }) {
  return (
    <div
      className="mt-3 rounded-r border-l-[3px] px-3.5 py-3 text-small"
      style={{
        borderColor: "var(--flag)",
        background: "color-mix(in oklab, var(--flag) 7%, transparent)",
        color: "var(--ink)",
      }}
    >
      {children}
    </div>
  );
}

/* --------------------------------------------------------------- footnote */

export function SourceLine({ children }: { children: ReactNode }) {
  return <p className="text-micro text-ink-faint mt-2 normal-case tracking-normal">{children}</p>;
}
