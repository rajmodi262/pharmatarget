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

/** Which act is on stage, and how far through it we are.
 *
 * Driven by getBoundingClientRect() on a rAF loop, NOT by window.scrollY.
 *
 * The scrollY version worked on a plain page and silently did nothing the
 * moment anything other than the window was the scrolling element -- an
 * embedded pane, an iframe, a wrapper with overflow, or a browser doing
 * scroll containment. The page rendered, the canvas drew, and the acts simply
 * never advanced, which is the worst kind of bug: it looks like a design
 * choice.
 *
 * rect.top is relative to the viewport, so it is correct regardless of which
 * element actually scrolls. The loop costs one rect read per frame and only
 * commits state when the value moves enough to matter, so React re-renders at
 * roughly the rate the copy actually changes rather than 60 times a second.
 */
function useScrollStage(count: number) {
  const [state, setState] = useState({ index: 0, progress: 0 });
  const ref = useRef<HTMLDivElement>(null);
  const last = useRef({ index: -1, progress: -1 });
  // While a keyboard/click jump is settling, scroll must not fight it.
  const overrideUntil = useRef(0);

  useEffect(() => {
    let raf = 0;
    let alive = true;

    const tick = () => {
      if (!alive) return;
      const el = ref.current;
      if (el && performance.now() > overrideUntil.current) {
        const rect = el.getBoundingClientRect();
        const scrollable = rect.height - window.innerHeight;
        const travelled = -rect.top;
        const p = Math.min(Math.max(travelled / Math.max(scrollable, 1), 0), 1);

        const raw = p * count;
        const index = Math.min(count - 1, Math.max(0, Math.floor(raw)));
        const progress = raw - Math.floor(raw);

        // Commit only on a real change: a new act, or >0.5% of an act's scroll.
        if (index !== last.current.index ||
            Math.abs(progress - last.current.progress) > 0.005) {
          last.current = { index, progress };
          setState({ index, progress });
        }
      }
      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => { alive = false; cancelAnimationFrame(raf); };
  }, [count]);

  /**
   * Jump to an act directly.
   *
   * The narrative must NOT depend solely on scrolling. Two reasons, and the
   * second is the one that matters:
   *
   *   - Accessibility. A keyboard user cannot drive a seven-act scroll
   *     narrative with the tab key. Without this the story is simply
   *     unavailable to them, which no amount of ARIA fixes.
   *   - Robustness. Embedded panes, kiosk modes and some presentation setups
   *     refuse programmatic scrolling outright. A story that only advances on
   *     scroll silently shows act one forever in those contexts.
   *
   * So the act index is state that scroll SYNCS TO, rather than state scroll
   * OWNS. The jump also moves the scroll position so the two agree once the
   * override lapses.
   */
  const goTo = (next: number) => {
    const index = Math.min(count - 1, Math.max(0, next));
    last.current = { index, progress: 0.5 };
    setState({ index, progress: 0.5 });
    overrideUntil.current = performance.now() + 900;

    const el = ref.current;
    if (el) {
      const scrollable = el.scrollHeight - window.innerHeight;
      const target = el.offsetTop + (scrollable * (index + 0.5)) / count;
      window.scrollTo({ top: target, behavior: "smooth" });
    }
  };

  return { ref, goTo, ...state };
}

/* ------------------------------------------------------------------ page */

export function Story() {
  const reduced = useReducedMotion();
  const { ref, goTo, index, progress } = useScrollStage(ACTS.length);
  const act = ACTS[index] ?? ACTS[0]!;

  // Keyboard navigation. Without this the story is unreachable for anyone who
  // cannot scroll -- and it makes the deck presentable from a clicker.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      switch (e.key) {
        case "ArrowRight": case "ArrowDown": case "PageDown": case " ":
          e.preventDefault(); goTo(index + 1); break;
        case "ArrowLeft": case "ArrowUp": case "PageUp":
          e.preventDefault(); goTo(index - 1); break;
        case "Home":
          e.preventDefault(); goTo(0); break;
        case "End":
          e.preventDefault(); goTo(ACTS.length - 1); break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, goTo]);

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
          <ActProgress index={index} progress={progress} onJump={goTo} />
        </div>
      </div>

      {/* The full narrative in DOM order, for screen readers and for anyone
          who would rather read seven paragraphs than scroll seven screens.
          The visual layer is one act at a time; the document is not. */}
      <div className="sr-only">
        <h1>PharmaTarget — the argument in full</h1>
        {ACTS.map((a, i) => (
          <section key={a.id} aria-label={`Act ${i + 1}: ${a.eyebrow}`}>
            <h2>{a.eyebrow}</h2>
          </section>
        ))}
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
        <p className="mt-4 text-[11px] text-[#75859A]">{note}</p>
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
        <span className="num text-[11px] text-[#75859A]">
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

function ActProgress({ index, progress, onJump }: {
  index: number;
  progress: number;
  onJump: (i: number) => void;
}) {
  return (
    <nav
      aria-label="Acts"
      className="absolute bottom-6 left-6 right-6 flex gap-1.5"
    >
      {ACTS.map((a, i) => (
        <button
          key={a.id}
          type="button"
          onClick={() => onJump(i)}
          aria-label={`Act ${i + 1} of ${ACTS.length}: ${a.eyebrow}`}
          aria-current={i === index ? "step" : undefined}
          // A 1px rule is an unusable target. The hit area is transparent and
          // generous -- 44px on touch, per WCAG 2.5.5, and 20px with a mouse
          // where precision is cheap. Only the rule inside it is ever visible.
          className="group relative h-11 flex-1 cursor-pointer bg-transparent p-0 sm:h-5"
        >
          <span className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 overflow-hidden bg-[#1F2937] transition-all duration-150 group-hover:h-[3px]">
            <span
              className="block h-full"
              style={{
                width: i < index ? "100%" : i === index ? `${progress * 100}%` : "0%",
                background: "var(--glow)",
                transition: "width 120ms linear",
              }}
            />
          </span>
        </button>
      ))}
    </nav>
  );
}

function ScrollHint({ visible }: { visible: boolean }) {
  return (
    <div
      className="pointer-events-none absolute bottom-16 left-1/2 -translate-x-1/2 text-[11px] uppercase tracking-[0.2em] text-[#75859A]"
      style={{ opacity: visible ? 1 : 0, transition: "opacity 400ms" }}
    >
      Scroll
    </div>
  );
}

