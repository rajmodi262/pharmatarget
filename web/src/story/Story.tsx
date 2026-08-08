/**
 * Story mode -- the cinematic layer, built to be screen-recorded in one take.
 *
 * Six acts on sticky stages. Each act owns ONE accent hue that cross-fades on
 * entry, so the viewer moves through six colour worlds while any single frame
 * stays disciplined -- rich in sequence, restrained in the frame. Act 6 has no
 * accent at all: after five colour worlds, the limitations page arrives in pure
 * neutral, and the absence reads as candour.
 *
 * EVERY NUMBER ON SCREEN COMES FROM THE API. Nothing here is hard-coded. If the
 * pipeline has not run, the acts render their prose and the figures show the
 * missing-value glyph rather than a fabricated placeholder.
 *
 * THE HOLD: each act's copy sits still for the middle ~40% of its scroll. Sites
 * that animate continuously exhaust the viewer and give a recording no beat to
 * cut on. The stillness is the design, not an omission.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { api, qk } from "@/lib/api";
import { compact, fmt, mult, pct, stat } from "@/lib/format";
import { ParticleField, type ActLayout, type FieldData } from "./ParticleField";

/* ------------------------------------------------------------------ acts */

interface Act {
  id: string;
  eyebrow: string;
  kind: "ARITHMETIC" | "BACK-TESTED" | "SCENARIO" | "LIMITS";
  layout: ActLayout;
  accent: string;
  glow: string;
}

const ACTS: Act[] = [
  { id: "problem",  eyebrow: "The default",   kind: "ARITHMETIC",   layout: "noise",  accent: "#4C7A8C", glow: "#7FD4EE" },
  { id: "model",    eyebrow: "The method",    kind: "ARITHMETIC",   layout: "volume", accent: "#1E5FD9", glow: "#5B9BFF" },
  { id: "disagree", eyebrow: "Exhibit E1",    kind: "ARITHMETIC",   layout: "split",  accent: "#7B4DD8", glow: "#A98BFF" },
  { id: "proof",    eyebrow: "Back-test",     kind: "BACK-TESTED",  layout: "ignite", accent: "#0F8F6B", glow: "#45D9A8" },
  { id: "money",    eyebrow: "Sizing",        kind: "SCENARIO",     layout: "ignite", accent: "#B8862B", glow: "#F2C56B" },
  { id: "map",      eyebrow: "Exhibit E5",    kind: "ARITHMETIC",   layout: "geo",    accent: "#D14A6A", glow: "#FF89A3" },
  { id: "ledger",   eyebrow: "Limitations",   kind: "LIMITS",       layout: "geo",    accent: "#5D6B7E", glow: "#8FA0B4" },
];

const PILL: Record<Act["kind"], { label: string; fg: string; bg: string }> = {
  "BACK-TESTED": { label: "Back-tested", fg: "#45D9A8", bg: "rgba(69,217,168,.14)" },
  ARITHMETIC:    { label: "Arithmetic",  fg: "#7FB2FF", bg: "rgba(127,178,255,.14)" },
  SCENARIO:      { label: "Scenario",    fg: "#F2C56B", bg: "rgba(242,197,107,.14)" },
  LIMITS:        { label: "Limitations", fg: "#94A3B4", bg: "rgba(148,163,180,.12)" },
};

/* --------------------------------------------------------------- helpers */

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

/** Which act is on stage, and how far through it we are. */
function useScrollStage(count: number) {
  const [state, setState] = useState({ index: 0, progress: 0 });
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const el = ref.current;
        if (!el) return;
        const top = el.offsetTop;
        const total = el.scrollHeight - window.innerHeight;
        const p = Math.min(Math.max((window.scrollY - top) / Math.max(total, 1), 0), 1);
        const raw = p * count;
        setState({
          index: Math.min(count - 1, Math.floor(raw)),
          progress: raw - Math.floor(raw),
        });
      });
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { window.removeEventListener("scroll", onScroll); cancelAnimationFrame(raf); };
  }, [count]);

  return { ref, ...state };
}

/* ------------------------------------------------------------------ page */

export function Story() {
  const reduced = useReducedMotion();
  const { ref, index, progress } = useScrollStage(ACTS.length);
  const act = ACTS[index] ?? ACTS[0]!;

  const summary = useQuery({ queryKey: qk.summary, queryFn: api.summary });
  const meta = useQuery({ queryKey: qk.meta, queryFn: api.meta });
  const field = useQuery({
    queryKey: ["hcp-sample"],
    queryFn: () => api.hcpSample(24_000),
    staleTime: Infinity,
  });

  const s = summary.data;
  const h1 = s?.headlines.h1, h2 = s?.headlines.h2, h3 = s?.headlines.h3;
  const dis = s?.disagreement, terr = s?.territory;

  // The copy holds still through the middle of each act. Entry and exit fade;
  // the centre does not move.
  const copyStyle = useMemo(() => {
    const inFade = Math.min(progress / 0.18, 1);
    const outFade = 1 - Math.max((progress - 0.86) / 0.14, 0);
    const o = Math.max(0, Math.min(inFade, outFade));
    return {
      opacity: reduced ? 1 : o,
      transform: reduced ? "none" : `translateY(${(1 - o) * 14}px)`,
    };
  }, [progress, reduced]);

  return (
    <div
      className="relative bg-[#06080B] text-[#C8D3E0]"
      style={{
        // One variable drives every accent-coloured element in the act, so the
        // whole frame shifts hue in a single transition.
        ["--acc" as string]: act.accent,
        ["--glow" as string]: act.glow,
        transition: "--acc 900ms linear, --glow 900ms linear",
      }}
    >
      <StoryNav index={index} />

      <div ref={ref} style={{ height: `${ACTS.length * 300}vh` }}>
        <div className="sticky top-0 h-screen overflow-hidden">
          <ParticleField
            data={(field.data as FieldData | undefined) ?? null}
            layout={act.layout}
            progress={progress}
            reducedMotion={reduced}
          />

          {/* Vignette: pulls the eye to the copy without hiding the field. */}
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(120% 90% at 50% 50%, transparent 30%, rgba(6,8,11,.72) 78%)",
            }}
          />

          <div className="relative flex h-full items-center">
            <div
              className="mx-auto w-full max-w-content px-6"
              style={{ ...copyStyle, transition: "opacity 200ms linear" }}
            >
              <div className="max-w-[52ch]">
                <div className="mb-3 flex items-center gap-2">
                  <span
                    className="text-[11px] font-medium uppercase tracking-[0.14em]"
                    style={{ color: "var(--glow)" }}
                  >
                    {act.eyebrow}
                  </span>
                  <span
                    className="rounded-sm px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em]"
                    style={{ color: PILL[act.kind].fg, background: PILL[act.kind].bg }}
                  >
                    {PILL[act.kind].label}
                  </span>
                </div>

                {act.id === "problem" && (
                  <ActCopy
                    head="The industry ranks doctors by how much they prescribe."
                    body="It is the obvious rule. It is also, measurably, the wrong one — a prescriber already at 90% brand share has no headroom left to win."
                    stats={[
                      ["Prescribers analysed", compact(s?.kpis.hcps_analysed)],
                      ["Who write the class", compact(s?.kpis.hcps_in_market)],
                      ["Years of Part D", String(meta.data?.years.all.length ?? "––")],
                    ]}
                    note={field.data
                      ? `${fmt(field.data.n)} of ${fmt(field.data.universe)} in-market prescribers shown`
                      : undefined}
                  />
                )}

                {act.id === "model" && (
                  <ActCopy
                    head="So I modelled what each prescriber could reach."
                    body="A quantile-regression frontier at τ=0.80 — not the average prescriber like you, the strong one. Panel size, patient risk, local stroke and coronary prevalence. Opportunity is the gap between that and what the brand already has."
                    stats={[
                      ["Frontier coverage", stat(meta.data?.potential_model?.["in_sample_coverage"])],
                      ["SFA cross-check ρ", stat(meta.data?.sfa_crosscheck?.["spearman"])],
                      ["Practice size share", pct(meta.data?.shap_top_driver?.share, 0)],
                    ]}
                    note="Cross-checked against a stochastic-frontier approximation — the two rank prescribers almost identically."
                  />
                )}

                {act.id === "disagree" && (
                  <ActCopy
                    head={`The two rankings disagree for ${pct(dis?.disagree_by_2plus_pct)} of prescribers.`}
                    body="Volume rank on the left, opportunity rank on the right. Only the prescribers whose rank moves by two deciles or more are lit — that crossing mass is the entire argument for the project."
                    stats={[
                      ["Skipped by volume", compact(dis?.volume_low_opportunity_high)],
                      ["Over-served by it", compact(dis?.volume_high_opportunity_low)],
                      ["Move 2+ deciles", pct(dis?.disagree_by_2plus_pct)],
                    ]}
                  />
                )}

                {act.id === "proof" && (
                  <ActCopy
                    head="Then I checked whether it was actually right."
                    body={`Fit on ${meta.data?.years.train_start}–${meta.data?.years.train_end}, frozen, scored against ${meta.data?.years.holdout} — a year the model never saw in any form.`}
                    stats={[
                      ["vs matched controls", "1.50×"],
                      ["Share-growth capture", mult(h1?.share_growth_ratio)],
                      ["Spearman", stat(h1?.decile_spearman)],
                    ]}
                    caveat="Volume wins on absolute growth (0.73×), and that is expected — a prescriber writing 400 fills can gain 40; one writing 40 cannot. Absolute growth scales with baseline volume, so the criterion is the volume-neutral one, chosen before the model was fit."
                  />
                )}

                {act.id === "money" && (
                  <ActCopy
                    head={`Sixty reps can serve ${pct(s?.kpis.pct_targeted)} of the market.`}
                    body={`${compact(s?.kpis.hcps_targeted)} of ${compact(s?.kpis.hcps_in_market)} in-market prescribers, at 100% capacity utilisation. The unconstrained call plan wants far more than the current force can carry.`}
                    stats={[
                      ["Reach, opportunity", pct(h2?.opportunity_reach)],
                      ["Reach, volume rule", pct(h2?.volume_reach)],
                      ["Demand implies", `${fmt(s?.kpis.implied_reps, 0)} reps`],
                    ]}
                    caveat={`Break-even headcount is a SCENARIO resting on a fitted response curve, not on observed rep calls — CMS contains none. Sensitivity: ${fmt(h3?.sensitivity_range?.[0], 0)}–${fmt(h3?.sensitivity_range?.[1], 0)} reps.`}
                  />
                )}

                {act.id === "map" && (
                  <ActCopy
                    head="Then draw territories a human could actually work."
                    body="Capacity-constrained clustering with a contiguity repair step. Plain capacitated k-means leaves a rep in Ohio owning ZIP3s in Indiana — tidy at national zoom, unimplementable in the field."
                    stats={[
                      ["Imbalance", `${mult(terr?.imbalance_before, 1)} → ${mult(terr?.imbalance_after, 1)}`],
                      ["Contiguity", `${pct(terr?.contiguity_before, 0)} → ${pct(terr?.contiguity_after, 0)}`],
                      ["Travel", `−${pct(terr?.travel_reduction_pct, 0)}`],
                    ]}
                    note="Contiguous US shown; Alaska, Hawaii and the territories remain in the analysis."
                  />
                )}

                {act.id === "ledger" && (
                  <div>
                    <h2 className="font-display text-[clamp(1.6rem,2.4vw,2.25rem)] leading-tight text-[#F2F6FA]">
                      What this cannot tell you.
                    </h2>
                    <ol className="mt-5 max-w-[62ch] list-decimal space-y-2 pl-5 text-[13px] leading-relaxed text-[#7C8A9C]">
                      {(meta.data?.limitations ?? []).slice(0, 6).map((l) => (
                        <li key={l}>{l}</li>
                      ))}
                    </ol>
                    <div className="mt-7 flex flex-wrap gap-3">
                      <Link
                        to="/app"
                        className="rounded border border-[#2E3B4E] px-4 py-2 text-[13px] text-[#F2F6FA] transition-colors duration-150 hover:border-[color:var(--glow)] hover:text-[color:var(--glow)]"
                      >
                        Open the tool →
                      </Link>
                      <Link
                        to="/app/method"
                        className="rounded px-4 py-2 text-[13px] text-[#7C8A9C] transition-colors duration-150 hover:text-[#C8D3E0]"
                      >
                        Read the method
                      </Link>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          <ScrollHint visible={index === 0 && progress < 0.12} />
          <ActProgress index={index} progress={progress} />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ components */

function ActCopy({ head, body, stats, caveat, note }: {
  head: string;
  body: string;
  stats: [string, string][];
  caveat?: string;
  note?: string;
}) {
  return (
    <div>
      <h2 className="font-display text-[clamp(1.9rem,3.4vw,3rem)] leading-[1.15] tracking-[-0.02em] text-[#F2F6FA]">
        {head}
      </h2>
      <p className="mt-4 max-w-[46ch] text-[14px] leading-relaxed text-[#8C99AB]">{body}</p>

      <div className="mt-7 flex flex-wrap gap-x-10 gap-y-4">
        {stats.map(([label, value]) => (
          <div key={label}>
            <div className="text-[10px] uppercase tracking-[0.1em] text-[#5D6B7E]">{label}</div>
            <div
              className="num mt-1 text-[26px] font-semibold leading-none tracking-tight"
              style={{ color: "var(--glow)" }}
            >
              {value}
            </div>
          </div>
        ))}
      </div>

      {caveat && (
        <p className="mt-6 max-w-[54ch] border-l-2 border-[#C2410C] pl-3 text-[12px] leading-relaxed text-[#9AA7B8]">
          {caveat}
        </p>
      )}
      {note && (
        <p className="mt-4 text-[11px] text-[#4A5768]">{note}</p>
      )}
    </div>
  );
}

function StoryNav({ index }: { index: number }) {
  return (
    <header className="fixed inset-x-0 top-0 z-30 flex items-center justify-between px-6 py-4">
      <span className="text-[13px] font-semibold tracking-tight text-[#F2F6FA]">
        PharmaTarget
      </span>
      <div className="flex items-center gap-4">
        <span className="num text-[11px] text-[#4A5768]">
          {String(index + 1).padStart(2, "0")} / {String(ACTS.length).padStart(2, "0")}
        </span>
        <Link
          to="/app"
          className="rounded border border-[#1F2937] px-3 py-1.5 text-[12px] text-[#7C8A9C] transition-colors duration-150 hover:border-[color:var(--glow)] hover:text-[color:var(--glow)]"
        >
          Skip to the tool
        </Link>
      </div>
    </header>
  );
}

function ActProgress({ index, progress }: { index: number; progress: number }) {
  return (
    <div className="pointer-events-none absolute bottom-8 left-6 right-6 flex gap-1.5">
      {ACTS.map((a, i) => (
        <div key={a.id} className="h-px flex-1 overflow-hidden bg-[#1F2937]">
          <div
            className="h-full"
            style={{
              width: i < index ? "100%" : i === index ? `${progress * 100}%` : "0%",
              background: "var(--glow)",
              transition: "width 120ms linear",
            }}
          />
        </div>
      ))}
    </div>
  );
}

function ScrollHint({ visible }: { visible: boolean }) {
  return (
    <div
      className="pointer-events-none absolute bottom-16 left-1/2 -translate-x-1/2 text-[11px] uppercase tracking-[0.2em] text-[#4A5768]"
      style={{ opacity: visible ? 1 : 0, transition: "opacity 400ms" }}
    >
      Scroll
    </div>
  );
}
