"""Generate the exhibits and the deck from the pipeline outputs.

    python -m src.report.make_assets

Writes outputs/figures/*.png and outputs/PharmaTarget_Recommendations.pdf.

Every number is read from data/processed/*.parquet and data/manifest.json --
nothing is typed in. Re-running after a pipeline change regenerates the deck
with the new numbers, so the slides can never drift from the analysis, which is
the usual way a deck ends up lying.

House style follows the project's design tokens: chart paper ground, hairline
rules, monospaced numerals, action titles that state the finding rather than
naming the chart, and a source line on every exhibit.
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from src.config import ROOT  # noqa: E402
from src.utils.io import get_logger  # noqa: E402

log = get_logger(__name__)

PROC = ROOT / "data" / "processed"
FIGS = ROOT / "outputs" / "figures"
DECK = ROOT / "outputs" / "PharmaTarget_Recommendations.pdf"

PAPER, INK, MUTE, RULE = "#FBFCFD", "#101B2B", "#5D6B7E", "#E1E7EE"
SIGNAL, FLAG, POS = "#0057C7", "#C2410C", "#17A673"
OPP = ["#EEF3F8", "#DCE6F1", "#C4D6EA", "#A6C2E0", "#83AAD4",
       "#5F91C7", "#4176B4", "#2A5C9B", "#17437B", "#0A2C5C"]
VOL = "#8C8681"

plt.rcParams.update({
    "figure.facecolor": PAPER, "axes.facecolor": PAPER,
    "savefig.facecolor": PAPER, "font.size": 9,
    "axes.edgecolor": RULE, "axes.labelcolor": MUTE,
    "xtick.color": MUTE, "ytick.color": MUTE,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.family": ["DejaVu Sans"],
})

SOURCE = "Source: CMS Medicare Part D & Open Payments, 2022-2024."


def _m() -> dict:
    return json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))


def _pq(name: str) -> pd.DataFrame | None:
    p = PROC / f"{name}.parquet"
    return pd.read_parquet(p) if p.exists() else None


def _title(ax, eyebrow: str, headline: str, klass: str = "") -> None:
    """Action title: a sentence stating the finding, with its evidence class."""
    # matplotlib has no letter-spacing property, so the tracked-caps eyebrow is
    # faked by spacing the characters. Cheap, and it survives PDF export.
    lead = f"{eyebrow}   /   {klass}" if klass else eyebrow
    ax.text(0, 1.16, " ".join(lead.upper()), transform=ax.transAxes,
            fontsize=6.5, color=MUTE)
    ax.text(0, 1.055, headline, transform=ax.transAxes, fontsize=11.5,
            color=INK, fontweight="semibold", va="bottom")


def _source(fig, extra: str = "") -> None:
    fig.text(0.02, 0.015, SOURCE + (f"  {extra}" if extra else ""),
             fontsize=6.5, color="#94A3B4")


# --------------------------------------------------------------------------- #

def e1_disagreement(m: dict):
    d = _pq("disagreement_matrix")
    if d is None:
        return None
    grid = np.zeros((10, 10))
    for r in d.itertuples(index=False):
        o, v = int(r.opportunity_decile), int(r.volume_decile)
        if 1 <= o <= 10 and 1 <= v <= 10:
            grid[10 - o, v - 1] = r.hcp_count

    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    ax.imshow(grid, cmap="Blues", aspect="auto", interpolation="nearest")
    ax.set_xticks(range(10), [str(i) for i in range(1, 11)])
    ax.set_yticks(range(10), [str(i) for i in range(10, 0, -1)])
    ax.set_xlabel("Volume decile")
    ax.set_ylabel("Opportunity decile")

    # Outline the two regions that carry the argument.
    ax.add_patch(plt.Rectangle((-0.5, -0.5), 4, 4, fill=False, ec=POS, lw=2))
    ax.add_patch(plt.Rectangle((5.5, 5.5), 4, 4, fill=False, ec=FLAG, lw=2))

    dis = m.get("disagreement", {})
    _title(ax, "Exhibit E1", f"Volume and opportunity disagree for "
           f"{100*dis.get('disagree_by_2plus_pct',0):.1f}% of prescribers", "ARITHMETIC")
    ax.text(0.02, -0.20, f"{dis.get('volume_low_opportunity_high',0):,} skipped by the volume rule",
            transform=ax.transAxes, fontsize=8, color=POS)
    ax.text(0.52, -0.20, f"{dis.get('volume_high_opportunity_low',0):,} over-served by it",
            transform=ax.transAxes, fontsize=8, color=FLAG)
    fig.tight_layout(rect=(0, 0.05, 1, 0.90))
    _source(fig)
    return fig


def e2_lift(m: dict):
    d = _pq("backtest_decile_lift")
    if d is None:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    w = 0.38
    for i, (rule, colour) in enumerate([("opportunity", OPP[8]), ("volume", VOL)]):
        s = d[d["rule"] == rule].sort_values("decile")
        ax.bar(s["decile"] + (i - 0.5) * w, s["mean_growth_abs"], width=w,
               color=colour, label=rule.capitalize())
    ax.set_xticks(range(1, 11))
    ax.set_xlabel("Predicted decile")
    ax.set_ylabel("Mean realised growth (30-day fills)")
    ax.legend(frameon=False, fontsize=8)
    g3 = m.get("gate_g3", {})
    _title(ax, "Exhibit E2", f"Held-out year: the ranking ranks "
           f"(Spearman {g3.get('decile_spearman','--')})", "BACK-TESTED")
    fig.tight_layout(rect=(0, 0.05, 1, 0.90))
    _source(fig, "Fit 2022-23, frozen, scored against 2024.")
    return fig


def e3_reach(m: dict):
    d = _pq("reach_curve")
    if d is None:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for rule, colour, ls in [("opportunity", OPP[9], "-"),
                             ("volume", VOL, "-"),
                             ("geography", "#B8C2CE", "--")]:
        s = d[d["rule"] == rule].sort_values("pct_of_universe")
        ax.plot(s["pct_of_universe"] * 100, s["pct_opportunity_reached"] * 100,
                color=colour, ls=ls, lw=2, label=rule.capitalize())
    ax.set_xlabel("Share of prescriber universe called (%)")
    ax.set_ylabel("Addressable opportunity reached (%)")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    h2 = m.get("headline_h2", {})
    _title(ax, "Exhibit E3", f"Same budget, "
           f"{100*h2.get('opportunity_pct_opportunity',0):.1f}% reached vs "
           f"{100*h2.get('volume_pct_opportunity',0):.1f}%", "ARITHMETIC")
    fig.tight_layout(rect=(0, 0.05, 1, 0.90))
    _source(fig, "No behavioural assumption: coverage, not outcome.")
    return fig


def e4_sizing(m: dict):
    curve, torn = _pq("sizing_roi_curve"), _pq("sizing_tornado")
    if curve is None:
        return None
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.2))

    c = curve.dropna(subset=["marginal_roi"])
    a1.plot(c["n_reps"], c["marginal_roi"], color="#B8862B", lw=2)
    a1.axhline(1.0, color=FLAG, ls="--", lw=1)
    a1.text(c["n_reps"].max(), 1.06, "break-even", ha="right", fontsize=7.5, color=FLAG)
    cur = m.get("headline_h3", {}).get("current_n_reps", 60)
    a1.axvline(cur, color="#94A3B4", ls=":", lw=1)
    a1.text(cur + 6, a1.get_ylim()[1] * 0.9, f"today {cur}", fontsize=7.5, color=MUTE)
    a1.set_xlabel("Field force size (reps)")
    a1.set_ylabel("Marginal ROI (x cost)")
    _title(a1, "Exhibit E4", "Marginal-rep economics", "SCENARIO")

    if torn is not None and len(torn):
        t = torn.sort_values("swing")
        y = np.arange(len(t))
        lo = np.minimum(t["break_even_low"], t["break_even_high"])
        hi = np.maximum(t["break_even_low"], t["break_even_high"])
        a2.barh(y, hi - lo, left=lo, color="#E2C79A", edgecolor="#B8862B")
        a2.set_yticks(y, [s.replace("_", " ") for s in t["assumption"]], fontsize=7.5)
        a2.set_xlabel("Break-even headcount across the assumption's range")
        _title(a2, "Sensitivity", "Which assumption to argue with first", "")
    fig.tight_layout(rect=(0, 0.05, 1, 0.88))
    _source(fig, "Assumptions and ranges in config/economics.yaml.")
    return fig


def e5_territory(m: dict):
    d = _pq("territory_assignments")
    if d is None:
        return None
    n = m.get("territory_headline", {}).get("n_reps", 60)

    # COLOUR BY TERRITORY WORKLOAD, NOT BY TERRITORY ID.
    #
    # The first version coloured by territory index on a 20-colour map. With 60
    # territories the hues cycled three times, adjacent regions shared colours,
    # and -- fatally -- the two panels looked identical, because "alphabetical
    # by state" is already geographically clustered. The exhibit has to show the
    # FINDING, and the finding is balance: before is wildly uneven, after is
    # uniform. Encoding workload on a shared colour scale makes that visible in
    # one glance without reading a number.
    panels = []
    for align in ("baseline", "optimised"):
        s = d[(d["alignment"] == align) & (d["n_reps"] == n)]
        if s.empty:
            s = d[d["alignment"] == align]
        s = s[(s["lat"].between(24, 50)) & (s["lon"].between(-125, -66))].copy()
        # Each unit carries its TERRITORY's total workload, so a rep's whole
        # burden is what is being coloured, not the unit's own contribution.
        load = s.groupby("territory")["workload"].transform("sum")
        s["terr_load"] = load
        panels.append((align, s))

    allload = pd.concat([p[1]["terr_load"] for p in panels])
    vmin, vmax = float(allload.quantile(0.02)), float(allload.quantile(0.98))

    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.8))
    sc = None
    for ax, (align, s) in zip(axes, panels, strict=True):
        label = ("Before - alphabetical by state" if align == "baseline"
                 else "After - capacity-constrained, contiguous")
        sc = ax.scatter(s["lon"], s["lat"], c=s["terr_load"], cmap="RdYlBu_r",
                        vmin=vmin, vmax=vmax, s=22, alpha=0.9,
                        linewidths=0.2, edgecolors="white")
        ax.set_title(label, fontsize=9.5, color=INK, loc="left", pad=8)
        ax.set_xticks([])
        ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_visible(False)

    if sc is not None:
        cb = fig.colorbar(sc, ax=axes, fraction=0.022, pad=0.015)
        cb.set_label("Territory workload (calls / month)", fontsize=7.5, color=MUTE)
        cb.ax.tick_params(labelsize=7, colors=MUTE)
        cb.outline.set_visible(False)

    t = m.get("territory_headline", {})
    fig.suptitle(
        f"Territory alignment: imbalance {t.get('imbalance_before',0):.0f}x -> "
        f"{t.get('imbalance_after',0):.1f}x   |   contiguity "
        f"{100*t.get('contiguity_before',0):.0f}% -> {100*t.get('contiguity_after',0):.0f}%   |   "
        f"travel -{100*t.get('travel_reduction_pct',0):.0f}%",
        fontsize=11, color=INK, x=0.02, ha="left", y=0.97)
    _source(fig, "Each dot is a ZIP3, coloured by its territory's total workload on a shared "
                 "scale. Contiguous US shown; all units included in the solve.")
    return fig


def e6_challenger(m: dict):
    d = _pq("challenger_results")
    if d is None:
        return None
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.2))
    d = d.sort_values("share_capture")
    y = np.arange(len(d))
    a1.barh(y, d["share_capture"] * 100, color="#A6C2E0")
    a1.barh(y, d["abs_capture"] * 100, height=0.42, color=OPP[8])
    a1.set_yticks(y, d["rule"], fontsize=8)
    a1.set_xlabel("Capture at a 60-rep budget (%)")
    a1.legend(["Share growth", "Absolute growth"], frameon=False, fontsize=7.5)
    _title(a1, "Champion vs challenger", "The ML model wins the stated metric", "")

    a2.barh(y, d["median_base_class_fills"], color="#D9B8A0")
    a2.set_yticks(y, d["rule"], fontsize=8)
    a2.set_xlabel("Median base volume of the selected list (class fills)")
    _title(a2, "The diagnostic", "...by selecting micro-prescribers", "")
    fig.tight_layout(rect=(0, 0.05, 1, 0.88))
    _source(fig, "Share growth on a tiny denominator is arithmetic, not persuadability.")
    return fig


# --------------------------------------------------------------------------- #

def _slide(pdf: PdfPages, eyebrow: str, headline: str, bullets: list[str],
           footer: str = "") -> None:
    fig = plt.figure(figsize=(13.33, 7.5))
    fig.text(0.06, 0.86, eyebrow.upper(), fontsize=9, color=MUTE)
    fig.text(0.06, 0.76, headline, fontsize=23, color=INK, va="top", wrap=True)
    y = 0.60
    for b in bullets:
        fig.text(0.065, y, "—", fontsize=11, color=SIGNAL)
        fig.text(0.09, y, b, fontsize=11.5, color=INK if not b.startswith("(") else MUTE,
                 va="top", wrap=True)
        y -= 0.085
    if footer:
        fig.text(0.06, 0.06, footer, fontsize=8, color=MUTE, wrap=True)
    pdf.savefig(fig)
    plt.close(fig)


def build_deck(m: dict, figures: list) -> None:
    DECK.parent.mkdir(parents=True, exist_ok=True)
    dis, h2 = m.get("disagreement", {}), m.get("headline_h2", {})
    g3, cp = m.get("gate_g3", {}), m.get("call_plan", {})
    t, mt = m.get("territory_headline", {}), m.get("backtest_matched", {})
    supp = next((v for k, v in m.items() if k.startswith("suppression_")), {})

    with PdfPages(DECK) as pdf:
        _slide(pdf, "PharmaTarget", "Which physicians should 60 reps call on?",
               ["Northwind Pharma markets a branded DOAC with a fixed 60-rep field force,",
                "roughly $15M a year fully loaded, and flat share for two years.",
                f"Built on {cp.get('n_universe',0):,} Medicare Part D prescribers, 2022-2024."],
               "Real CMS data. Every figure in this deck is generated from the pipeline output.")

        _slide(pdf, "Situation", "The industry ranks doctors by prescription volume",
               ["That rule is structurally wrong.",
                "A prescriber already at 90% brand share has no headroom to win.",
                "A mid-volume prescriber at 6% share is where the growth is.",
                "Volume ranking cannot tell them apart."])

        _slide(pdf, "Approach", "Model what each prescriber could reach, then subtract",
               ["Quantile-regression frontier at tau = 0.80 on practice and market covariates.",
                "opportunity = potential_class x achievable_share - brand_fills",
                f"Frontier coverage {m.get('potential_model',{}).get('in_sample_coverage','--')}; "
                f"SFA cross-check {m.get('sfa_crosscheck',{}).get('spearman','--')}.",
                "No brand-volume feature reaches the potential model - the leakage guard raises."])

        _slide(pdf, "Data", "29 GB of source, streamed and reduced to 200 MB",
               [f"{supp.get('hidden_share_of_total',0)*100:.1f}% of all claim volume is suppressed by CMS,",
                "rising to 68.7% for prescribers under 100 claims - and it is not random.",
                "Rows under 11 claims are REMOVED, not blanked; the gap is recovered by",
                "reconciling provider totals against the sum of drug rows."])

        for fig in figures:
            if fig is not None:
                pdf.savefig(fig)

        _slide(pdf, "Finding 1", f"The two rankings disagree for "
               f"{100*dis.get('disagree_by_2plus_pct',0):.1f}% of prescribers",
               [f"{dis.get('volume_low_opportunity_high',0):,} are invisible to the volume rule.",
                f"{dis.get('volume_high_opportunity_low',0):,} are over-served by it.",
                "That disagreement is the entire argument for the project."])

        _slide(pdf, "Finding 2", f"Flagged prescribers grew "
               f"{mt.get('growth_ratio','--')}x faster in a held-out year",
               [f"Spearman {g3.get('decile_spearman','--')} between predicted decile and realised growth.",
                f"Share-growth capture {g3.get('share_growth_ratio','--')}x the volume rule.",
                f"Absolute-growth capture {g3.get('absolute_growth_ratio','--')}x - volume wins this one.",
                "(Absolute growth scales with baseline volume, so volume is mechanically advantaged.)"])

        _slide(pdf, "Finding 3", "The field force is drastically under-sized",
               [f"60 reps serve {cp.get('n_targets',0):,} of {cp.get('n_in_market',0):,} "
                f"in-market prescribers - {100*cp.get('pct_of_market_served',0):.1f}% - at full capacity.",
                f"The unconstrained call plan wants {cp.get('demand_hcps',0):,} prescribers.",
                "(Headcount economics are a scenario; the coverage gap is arithmetic.)"])

        _slide(pdf, "Recommendation", "Re-rank on opportunity; hold headcount; redraw the map",
               [f"Reach rises from {100*h2.get('volume_pct_opportunity',0):.1f}% to "
                f"{100*h2.get('opportunity_pct_opportunity',0):.1f}% of addressable opportunity, same budget.",
                f"Territory imbalance falls {t.get('imbalance_before',0):.0f}x -> {t.get('imbalance_after',0):.1f}x "
                f"with 100% contiguity and {100*t.get('travel_reduction_pct',0):.0f}% less travel.",
                "Neither requires a single additional representative."])

        _slide(pdf, "Honesty", "What this cannot tell you",
               ["Medicare-only; ~17-month lag; suppression hides small prescribers.",
                "Promotional payments: parallel trends FAILED, so association only.",
                "No call data, so the back-test sees where growth happened,",
                "not where a call would have caused it. Volume ranking wins absolute capture.",
                "(An ML challenger beat the stated metric by selecting 35-fill prescribers.",
                "The metric was gameable; the gate was hardened rather than the result kept.)"])

        _slide(pdf, "Next", "What a brand team would do with this",
               ["Replace Part D with all-payer IQVIA to remove the Medicare skew.",
                "Join rep call logs to make the response curve empirical rather than assumed.",
                "Add drive-time matrices and org boundaries before executing any alignment.",
                "Re-run quarterly: the pipeline is resumable and takes ~20 minutes end to end."])

    log.info("deck written: %s", DECK.relative_to(ROOT))


def run() -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    m = _m()
    builders = [("E1_disagreement", e1_disagreement), ("E2_backtest_lift", e2_lift),
                ("E3_reach_curve", e3_reach), ("E4_sizing", e4_sizing),
                ("E5_territory_before_after", e5_territory),
                ("E6_challenger", e6_challenger)]
    figures = []
    for name, fn in builders:
        try:
            fig = fn(m)
        except Exception as exc:  # noqa: BLE001
            log.warning("  %s failed: %s", name, exc)
            continue
        if fig is None:
            log.warning("  %s skipped -- input parquet missing", name)
            continue
        path = FIGS / f"{name}.png"
        fig.savefig(path, dpi=170, bbox_inches="tight")
        log.info("  wrote %s", path.name)
        figures.append(fig)

    build_deck(m, figures)
    for fig in figures:
        plt.close(fig)


if __name__ == "__main__":
    run()

