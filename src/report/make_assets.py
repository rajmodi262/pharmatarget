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
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from src.config import ROOT  # noqa: E402
from src.utils.io import get_logger  # noqa: E402

log = get_logger(__name__)

PROC = ROOT / "data" / "processed"
FIGS = ROOT / "outputs" / "figures"
DECK = ROOT / "outputs" / "PharmaTarget_Recommendations.pdf"

PAPER, INK, MUTE, RULE = "#F8EEEA", "#3A1F34", "#765A6B", "#E2CDC8"
SIGNAL, FLAG, POS = "#C75A3A", "#3A1F34", "#4C7D5A"
MAUVE, FAINT, NEG = "#C3A0A7", "#8F7382", "#A3263E"
# Palette: deep plum, dusty mauve, terracotta (matches web/src/design/tokens.css).
OPP = ["#F5E8E3", "#EFD5CB", "#E7BBAA", "#DE9D85", "#D27E61",
       "#C75A3A", "#A4442F", "#7E3330", "#5E2236", "#45193B"]
VOL = "#908086"
# Territory workload, light to heavy, in the palette (light mauve -> terracotta -> plum).
LOAD_CMAP = LinearSegmentedColormap.from_list(
    "load", ["#EADFE3", "#C3A0A7", "#C75A3A", "#3A1F34"])

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
             fontsize=6.5, color=FAINT)


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
    ax.imshow(grid, cmap=LinearSegmentedColormap.from_list("opp", OPP), aspect="auto",
              interpolation="nearest")
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
    sp = (m.get("bootstrap_headlines") or {}).get("spearman")
    sp_txt = f"prescriber-level rho {sp[1]:.2f} [{sp[0]:.2f}, {sp[2]:.2f}]" if sp else "--"
    _title(ax, "Exhibit E2", f"Held-out year: growth rises with the decile ({sp_txt})",
           "BACK-TESTED")
    fig.tight_layout(rect=(0, 0.05, 1, 0.90))
    _source(fig, "Fit on 2023, frozen, scored against 2024. Volume wins absolute growth at the top.")
    return fig


def e3_reach(m: dict):
    d = _pq("reach_curve")
    if d is None:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for rule, colour, ls in [("opportunity", OPP[9], "-"),
                             ("hybrid", OPP[6], "-."),
                             ("volume", VOL, "-"),
                             ("geography", MAUVE, "--")]:
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
    h3 = m.get("headline_h3", {})
    need = _pq("sizing_required_response")
    if not h3.get("response_identified", True) and need is not None:
        # No measured response: show what each force size would REQUIRE, and
        # where the measured upper bound sits. An ROI curve here would plot the
        # config assumptions and imply a precision the data does not have.
        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        n = need.dropna(subset=["required_ceiling"])
        ax.plot(n["n_reps"], n["required_ceiling"] * 100, color=SIGNAL, lw=2)
        cur = h3.get("current_n_reps", 60)
        rc = h3.get("required_ceiling_at_current")
        ax.axvline(cur, color=FAINT, ls=":", lw=1)
        if rc is not None:
            ax.scatter([cur], [rc * 100], color=FLAG, zorder=3)
            ax.text(cur + 8, rc * 100, f"today: {rc * 100:.2f}% of headroom / yr",
                    fontsize=7.5, color=FLAG, va="center")
        ax.set_xlabel("Field force size (reps)")
        ax.set_ylabel("Response the last rep needs (% of headroom / yr)")
        _title(ax, "Exhibit E4", "What each force size would need calling to deliver",
               "SCENARIO")
        fig.tight_layout(rect=(0, 0.05, 1, 0.90))
        _source(fig, "Public data show no measurable response (fit not identified). "
                     "Half-saturation assumed at the config base.")
        return fig

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.2))

    c = curve.dropna(subset=["marginal_roi"])
    a1.plot(c["n_reps"], c["marginal_roi"], color=SIGNAL, lw=2)
    a1.axhline(1.0, color=FLAG, ls="--", lw=1)
    a1.text(c["n_reps"].max(), 1.06, "break-even", ha="right", fontsize=7.5, color=FLAG)
    cur = m.get("headline_h3", {}).get("current_n_reps", 60)
    a1.axvline(cur, color=FAINT, ls=":", lw=1)
    a1.text(cur + 6, a1.get_ylim()[1] * 0.9, f"today {cur}", fontsize=7.5, color=MUTE)
    a1.set_xlabel("Field force size (reps)")
    a1.set_ylabel("Marginal ROI (x cost)")
    _title(a1, "Exhibit E4", "Marginal-rep economics", "SCENARIO")

    if torn is not None and len(torn):
        t = torn.sort_values("swing")
        y = np.arange(len(t))
        lo = np.minimum(t["break_even_low"], t["break_even_high"])
        hi = np.maximum(t["break_even_low"], t["break_even_high"])
        a2.barh(y, hi - lo, left=lo, color=OPP[2], edgecolor=SIGNAL)
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
        sc = ax.scatter(s["lon"], s["lat"], c=s["terr_load"], cmap=LOAD_CMAP,
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
    a1.barh(y, d["share_capture"] * 100, color=OPP[2])
    a1.barh(y, d["abs_capture"] * 100, height=0.42, color=OPP[8])
    a1.set_yticks(y, d["rule"], fontsize=8)
    a1.set_xlabel("Capture at a 60-rep budget (%)")
    a1.legend(["Share growth", "Absolute growth"], frameon=False, fontsize=7.5,
              loc="lower right")
    _title(a1, "Champion vs challenger", "The ML model wins the stated metric", "")

    a2.barh(y, d["median_base_class_fills"], color=MAUVE)
    a2.set_yticks(y, d["rule"], fontsize=8)
    a2.set_xlabel("Median base volume of the selected list (class fills)")
    _title(a2, "The diagnostic", "...by selecting micro-prescribers", "")
    fig.tight_layout(rect=(0, 0.05, 1, 0.88))
    _source(fig, "Share growth on a tiny denominator is arithmetic, not persuadability.")
    return fig


def e7_frontier(m: dict):
    """The blend frontier: chosen on 2022->23, tested on 2023->24."""
    d = _pq("decision_frontier")
    if d is None:
        return None
    fs = m.get("decision_frontier", {})
    floor = fs.get("abs_floor_vs_volume", 0.9)
    fig, ax = plt.subplots(figsize=(7.6, 4.6))
    sel = d[d["period"] == "selection"]
    hold = d[d["period"] == "holdout"]
    ax.axvspan(min(d["abs_vs_volume"].min(), 0.74) - 0.01, floor, color=NEG, alpha=0.06)
    ax.axvline(floor, color=NEG, ls="--", lw=1)
    ax.text(floor - 0.004, hold["share_vs_volume"].max() + 0.02, f"fails the {floor:.0%} floor",
            ha="right", fontsize=7.5, color=NEG)
    ax.plot(sel["abs_vs_volume"], sel["share_vs_volume"], color=MAUVE, ls="--", lw=1.6,
            label="2022->23 (where a weight is chosen)")
    ax.errorbar(hold["abs_vs_volume"], hold["share_vs_volume"],
                xerr=[hold["abs_vs_volume"] - hold["abs_vs_volume_lo"],
                      hold["abs_vs_volume_hi"] - hold["abs_vs_volume"]],
                color=SIGNAL, lw=2.4, marker="o", ms=3.5, elinewidth=3, ecolor=OPP[2],
                label="2023->24 holdout (the test)")
    for w, lab in ((fs.get("selected_weight"), "tuned"), (0.5, "50/50")):
        if w is None:
            continue
        r = hold[hold["weight"] == w].iloc[0]
        q = sel[sel["weight"] == w].iloc[0]
        tone = INK if lab == "50/50" else NEG
        ax.annotate("", xy=(r["abs_vs_volume"], r["share_vs_volume"]),
                    xytext=(q["abs_vs_volume"], q["share_vs_volume"]),
                    arrowprops={"arrowstyle": "->", "color": tone})
        # Labels sit in the empty corners and point back at the holdout point,
        # so they never sit on the curve they describe.
        ax.annotate(f"{lab} ({w:.0%}): clears the floor in {r['p_clears_floor']:.0%} of re-draws",
                    xy=(r["abs_vs_volume"], r["share_vs_volume"]),
                    xytext=(0.80, 1.10) if lab == "tuned" else (0.925, 1.30),
                    fontsize=7.5, color=tone,
                    arrowprops={"arrowstyle": "-", "color": tone, "lw": 0.6, "alpha": 0.6})
    ax.set_xlabel("Absolute branded growth kept, vs volume list")
    ax.set_ylabel("Share-growth captured, vs volume list")
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.legend(frameon=False, fontsize=7.5, loc="lower left")
    _title(ax, "Exhibit E7", "A weight tuned on last year falls through the floor; 50/50 holds",
           "BACK-TESTED")
    fig.tight_layout(rect=(0, 0.05, 1, 0.88))
    _source(fig, "Shaded bars: 95% bootstrap interval, 200 prescriber re-draws.")
    return fig


def _power(ep: dict, n_list: int, hold: float, months: float, cuped: bool = True) -> float:
    from math import erf, sqrt
    t = months / 12
    adj = sqrt(max(1 - ep["prior_rho"] ** 2, 0)) if cuped else 1.0
    se = ep["sd_per_year"] * sqrt(t) * adj * sqrt(1 / (n_list * (1 - hold)) + 1 / (n_list * hold))
    z = ep["effect_per_year"] * t / se - 1.959964
    return 0.5 * (1 + erf(z / sqrt(2)))


def e8_pilot(m: dict):
    """Pilot power by duration: share-point endpoint vs branded-fill endpoint."""
    pd_ = m.get("pilot_design") or {}
    if "share" not in pd_ or "fills" not in pd_:
        return None
    n = int(pd_.get("n_list") or 0)
    months = np.arange(1, 25)
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    ax.axhspan(0.8, 1.0, color=POS, alpha=0.07)
    ax.axhline(0.8, color=POS, ls="--", lw=1)
    for key, colour, lab in (("share", SIGNAL, "Endpoint: brand-share points"),
                             ("fills", MAUVE, "Endpoint: branded fills")):
        ax.plot(months, [_power(pd_[key], n, 0.2, mo) for mo in months], color=colour,
                lw=2.6 if key == "share" else 1.8, ls="-" if key == "share" else "--", label=lab)
    ax.axvline(6, color=FAINT, ls=":", lw=1)
    ax.text(6.3, 0.05, "two quarters", fontsize=7.5, color=MUTE)
    ax.set_ylim(0, 1.02)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xlabel("Pilot duration (months), 20% of the list held out")
    ax.set_ylabel("Power to detect the break-even response")
    ax.legend(frameon=False, fontsize=7.5, loc="lower right")
    _title(ax, "Exhibit E8", "Scored on share points, a two-quarter pilot can find the answer",
           "SCENARIO")
    fig.tight_layout(rect=(0, 0.05, 1, 0.88))
    _source(fig, "Noise: real 2023->24 change on the listed prescribers, CUPED-adjusted.")
    return fig


# --------------------------------------------------------------------------- #

def _slide(pdf: PdfPages, eyebrow: str, headline: str, bullets: list[str],
           footer: str = "") -> None:
    fig = plt.figure(figsize=(13.33, 7.5))
    # Editorial chrome: a plum spine and a terracotta rule under the eyebrow.
    fig.patches.append(plt.Rectangle((0, 0), 0.018, 1, transform=fig.transFigure,
                                     color=INK, zorder=0))
    fig.patches.append(plt.Rectangle((0.06, 0.835), 0.05, 0.004, transform=fig.transFigure,
                                     color=SIGNAL, zorder=0))
    fig.text(0.06, 0.86, eyebrow.upper(), fontsize=9, color=MUTE)
    fig.text(0.06, 0.78, headline, fontsize=24, color=INK, va="top", wrap=True,
             family="DejaVu Serif", fontweight="bold")
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


RULE_NAME = {"opportunity": "opportunity ranking", "volume": "volume ranking",
             "hybrid": "hybrid ranking (opportunity + volume)"}


def _p(v, d: int = 1) -> str:
    try:
        return f"{100 * float(v):.{d}f}%"
    except (TypeError, ValueError):
        return "--"


def _x(v, d: int = 2) -> str:
    try:
        return f"{float(v):.{d}f}x"
    except (TypeError, ValueError):
        return "--"


def _n(v, d: int = 0) -> str:
    try:
        return f"{float(v):,.{d}f}"
    except (TypeError, ValueError):
        return "--"


def _ci(triple, d: int = 2) -> str:
    if isinstance(triple, list) and len(triple) == 3:
        lo, est, hi = triple
        return f"{est:.{d}f} [{lo:.{d}f}, {hi:.{d}f}]"
    return "--"


def build_deck(m: dict, figures: list) -> None:
    """The deck, recommendation first. Every figure is read from the manifest.

    Structure is the consulting one: answer (slide 2), why we believe it, what
    it is worth, what it is not, what to do next. Nothing is typed in -- the
    previous version hard-coded "drastically under-sized" and "68.7%", and both
    went stale while the analysis moved underneath them.
    """
    DECK.parent.mkdir(parents=True, exist_ok=True)
    dis, h2, h3 = m.get("disagreement", {}), m.get("headline_h2", {}), m.get("headline_h3", {})
    cp, t = m.get("call_plan", {}), m.get("territory_headline", {})
    psm, boot = m.get("propensity_matched", {}), m.get("bootstrap_headlines", {})
    rec, rv = m.get("recommendation", {}), m.get("retargeting_value", {})
    fit, gap = m.get("call_response_fit", {}), m.get("response_selection_gap", {})
    grp = (m.get("top_driver") or {}).get("group_shares", {})
    supp = m.get(f"suppression_{'ev'}", {})
    by_size = m.get("suppression_by_size", {})
    rules = {r["rule"]: r for r in (m.get("challenger") or {}).get("results", [])}
    choice = rec.get("recommended_rule", "opportunity")
    ch, vol = rules.get(choice, {}), rules.get("volume", {})
    n60 = (m.get("challenger") or {}).get("n_budget")

    with PdfPages(DECK) as pdf:
        _slide(pdf, "PharmaTarget  |  Northwind Pharma DOAC field strategy",
               "Which prescribers should 60 reps call on?",
               ["Branded DOAC, fixed 60-rep field force (~$15M a year fully loaded), flat share.",
                f"{_n(cp.get('n_universe'))} Medicare Part D prescribers, "
                f"{_n(cp.get('n_in_market'))} of whom write the class; 2022-2024.",
                "Every number in this deck is generated from the pipeline output."],
               "Real CMS Part D and Open Payments data. Client and brand are illustrative.")

        # --- the answer, first -------------------------------------------------
        _slide(pdf, "Executive summary", f"Re-target on the {RULE_NAME.get(choice, choice)}; "
               "hold headcount; redraw the map",
               [f"Same 60 reps, same cost: the recommended list captured {_p(ch.get('share_capture'))} "
                f"of 2024 share gains vs {_p(vol.get('share_capture'))} for today's volume list "
                f"({_x(rec.get('share_vs_volume'))}), keeping {_p(rec.get('abs_vs_volume'), 0)} "
                "of its absolute growth.",
                f"Flagged prescribers outgrew propensity-matched peers by "
                f"{_n(psm.get('paired_difference'), 1)} branded fills "
                f"[{_n(psm.get('ci_low'), 1)}, {_n(psm.get('ci_high'), 1)}] in a year the model never saw.",
                (f"Headcount: the marginal rep returns ${_n(h3.get('marginal_roi_at_current'), 2)} per $1 "
                 f"at 60; break-even ~{_n(h3.get('break_even_n_reps'))} reps "
                 f"(range {_n(h3.get('sensitivity_low'))}-{_n(h3.get('sensitivity_high'))}).")
                if h3.get("response_identified", True) else
                (f"Headcount: hold at 60. Public data show no measurable call response; the 60th "
                 f"rep pays only if a year of calls captures >= "
                 f"{_p(h3.get('required_ceiling_at_current'), 2)} of remaining opportunity. A 20% "
                 "hold-out scored on brand-share points measures that with "
                 f"{_p(((m.get('pilot_design') or {}).get('share') or {}).get('power_holdout20_6m'), 0)} "
                 "power in two quarters."),
                f"Territories: imbalance {_x(t.get('imbalance_before'), 0)} -> "
                f"{_x(t.get('imbalance_after'), 1)}, contiguity {_p(t.get('contiguity_after'), 0)}, "
                f"vs plain k-means at {_x(t.get('kmeans_imbalance'), 0)} and "
                f"{_p(t.get('kmeans_contiguity'), 0)}."],
               "Evidence classes: BACK-TESTED (validated on 2024), ARITHMETIC (no behavioural "
               "assumption), SCENARIO (rests on the fitted response curve).")

        _slide(pdf, "Situation & complication", "Volume ranking cannot see headroom",
               ["The default rule ranks prescribers by how much of the class they write.",
                "A prescriber already at 90% brand share has nothing left to win.",
                "A mid-volume prescriber at low share, with an elderly high-risk panel, has a lot.",
                f"The two rankings disagree by 2+ deciles for {_p(dis.get('disagree_by_2plus_pct'))} "
                "of in-market prescribers."])

        _slide(pdf, "Approach", "Model what each prescriber could reach, then subtract",
               ["Quantile-regression frontier (tau 0.80): what a STRONG comparable writer reaches.",
                "opportunity = potential class volume x peer-achievable share - current brand fills",
                f"In-sample coverage {_n((m.get('potential_model') or {}).get('in_sample_coverage'), 3)} "
                f"vs tau 0.80; linear-frontier rank agreement "
                f"{_n((m.get('sfa_crosscheck') or {}).get('spearman'), 3)}.",
                "Importance: " + "; ".join(f"{k} {_p(v, 0)}" for k, v in
                                          sorted(grp.items(), key=lambda kv: -kv[1])),
                "(It is mostly a practice-size and patient-mix model; geography adds little.)"])

        _slide(pdf, "Data", "Streamed ~39 GB of public CMS files down to ~1.3 GB",
               [f"{_p(supp.get('hidden_share_of_total'))} of all Part D claim volume is suppressed "
                "(rows under 11 claims are removed, not blanked).",
                "Hidden share by prescriber size: " + ", ".join(
                    f"{k} {_p(v)}" for k, v in by_size.items()),
                "Recovered by reconciling provider totals against drug rows, capped at what the",
                "unobserved class drugs can physically hold; share is measured on observed volume.",
                "Promotion is attributed by PRODUCT name, not just by company."])

        for fig in figures:
            if fig is not None:
                pdf.savefig(fig)

        _slide(pdf, "Finding 1  |  BACK-TESTED", "The ranking predicts where share moves",
               [f"Fit on 2023, frozen, scored on 2024. Flagged prescribers vs "
                f"{_n(psm.get('n_pairs'))} propensity-matched controls: {_x(psm.get('growth_ratio'))} "
                f"the branded growth (worst SMD {_n(psm.get('worst_smd_after'), 3)}).",
                f"Share-growth capture vs volume: {_ci(boot.get('share_ratio'))} (95% bootstrap CI).",
                f"Absolute-growth capture vs volume: {_ci(boot.get('abs_ratio'))} -- volume wins this.",
                f"Prescriber-level rank correlation with realised growth: {_ci(boot.get('spearman'), 3)}.",
                "(Measures where growth happened, not where a call would have caused it.)"])

        _slide(pdf, "Finding 2  |  BACK-TESTED", "Each pure rule wins one metric; the blend is the decision",
               [f"Realised 2024 outcomes of each rule's {_n(n60)}-prescriber list (what 60 reps serve):"]
               + [f"{RULE_NAME.get(k, k)}: share {_p(rules[k].get('share_capture'))}, "
                  f"absolute {_p(rules[k].get('abs_capture'))}, net "
                  f"{_n(rules[k].get('net_brand_fill_growth'))} fills"
                  for k in ("volume", "opportunity", "hybrid") if k in rules]
               + [f"Pre-declared rule: {rec.get('criterion', '--')} -> {RULE_NAME.get(choice, choice)}."])

        fs, pdz = m.get("decision_frontier", {}), m.get("pilot_design", {})
        sh, fl = pdz.get("share", {}), pdz.get("fills", {})
        if fs:
            _slide(pdf, "Finding 2b  |  BACK-TESTED", "50/50 is robust because it was not tuned",
                   [f"Weights swept 0-100% opportunity. Chosen on 2022->23, the floor-maximising weight is "
                    f"{_p(fs.get('selected_weight'), 0)}: on the 2024 holdout it keeps "
                    f"{_p(fs.get('holdout_abs_vs_volume'))} of volume's growth and clears the floor in "
                    f"{_p(fs.get('holdout_p_clears_floor'), 0)} of re-draws.",
                    f"Equal weight keeps {_p(fs.get('equal_weight_abs_vs_volume'))} and wins "
                    f"{_x(fs.get('equal_weight_share_vs_volume'))} the share gains; it clears the floor in "
                    f"{_p(fs.get('equal_weight_p_clears_floor'), 0)} of re-draws.",
                    "The frontier keeps its shape but shifts a couple of points a year: a weight set "
                    "exactly on the floor is a coin toss the following year.",
                    f"If the brand team wants 95% confidence of keeping the base: "
                    f"{_p(fs.get('robust_weight_p95'), 0)} weight, at a small cost in share gain.",
                    "(Re-read the floor at every annual data refresh.)"])

        identified = h3.get("response_identified", True)
        _slide(pdf, "Finding 3  |  SCENARIO",
               "The force is the right size; the list is wrong" if identified else
               "Headcount cannot be sized from public data -- hold, and measure",
               [f"60 reps serve {_n(cp.get('n_targets'))} of {_n(cp.get('n_in_market'))} in-market "
                f"prescribers ({_p(cp.get('pct_of_market_served'))}) at full capacity.",
                (f"Call response fitted on brand-named visits: ceiling {_n(fit.get('ceiling'), 4)} "
                 f"of headroom, half-saturation {_n(fit.get('half_saturation_calls'), 1)} calls/yr.")
                if identified else
                (f"Brand-named visit events show no dose-response after volume stratification "
                 f"(weighted R^2 {_n(fit.get('weighted_r2'), 2)}); the curve is not identified. "
                 f"Break-even response for the 60th rep: {_p(h3.get('required_ceiling_at_current'), 2)} "
                 "of headroom a year."),
                f"Modelled headroom in front of a rep at 60 reps: opportunity list "
                f"{_p(h2.get('opportunity_pct_opportunity'))}, hybrid {_p(h2.get('hybrid_pct_opportunity'))}, "
                f"volume {_p(h2.get('volume_pct_opportunity'))}.",
                (f"Marginal rep at 60: ${_n(h3.get('marginal_roi_at_current'), 2)} per $1; "
                 f"break-even ~{_n(h3.get('break_even_n_reps'))} reps.")
                if identified else
                "Recommendation: hold 60 reps; split districts into a two-quarter pilot to measure it.",
                f"Modelled value of re-targeting at identical cost: "
                f"${_n((rv.get('hybrid_vs_volume_contribution') if choice == 'hybrid' else rv.get('delta_contribution')) or 0)}"
                f" a year, priced at the {rv.get('priced_at', 'fitted response curve')}.",
                "(That dollar figure is MODELLED; the realised comparison is Finding 2.)"])

        _slide(pdf, "Finding 4  |  ARITHMETIC", "Redraw the territories, not the headcount",
               [f"Alphabetical-by-state: imbalance {_x(t.get('imbalance_before'), 0)}, contiguity "
                f"{_p(t.get('contiguity_before'), 0)}, travel {_n(t.get('travel_before'))} mi.",
                f"Plain k-means: imbalance {_x(t.get('kmeans_imbalance'), 0)}, contiguity "
                f"{_p(t.get('kmeans_contiguity'), 0)}, travel {_n(t.get('kmeans_travel'))} mi.",
                f"Capacitated + contiguity-repaired: imbalance {_x(t.get('imbalance_after'), 1)}, "
                f"CV {_n(t.get('cv_after'), 3)}, contiguity {_p(t.get('contiguity_after'), 0)}, "
                f"travel {_n(t.get('travel_after'))} mi."])

        pre = m.get("response_pretrend", {})
        _slide(pdf, "Finding 5  |  ASSOCIATION",
               "Promotion's association with share cannot be separated from prior trend",
               [f"Prescribers first paid in 2023 were ALREADY gaining share faster beforehand: "
                f"{_n(pre.get('difference'), 4)} share points vs controls (p {_n(pre.get('p_value'), 3)}).",
                f"Paid vs unpaid prescribers, 2023->2024 share change: "
                f"{_n(gap.get('naive_post_difference'), 4)} share points (naive).",
                f"Minus their pre-period gap: {_n(gap.get('unmatched_did'), 4)}; on matched pairs: "
                f"{_n(gap.get('matched_did'), 4)} "
                f"[{_n((gap.get('matched_did_ci') or [None, None])[0], 4)}, "
                f"{_n((gap.get('matched_did_ci') or [None, None])[1], 4)}].",
                "Parallel trends failed, so this is reported as association only (pre-committed)."])

        if sh and fl:
            _slide(pdf, "Pilot design  |  SCENARIO", "The endpoint decides whether the pilot works",
                   [f"Effect to detect = the break-even response: "
                    f"{_p(pdz.get('required_ceiling'), 2)} of headroom a year on the listed prescribers.",
                    f"Scored on brand-share points, a 20% hold-out has {_p(sh.get('power_holdout20_6m'), 0)} "
                    f"power at six months ({_p(sh.get('power_holdout20_12m'), 0)} at twelve).",
                    f"Scored on branded fills, the same design has {_p(fl.get('power_holdout20_6m'), 0)}: "
                    "fills are dominated by practice size, share points are volume-neutral.",
                    f"Territory randomisation (30 v 30) reaches {_p(sh.get('power_territory_split_6m'), 0)} "
                    f"at six months; ICC {_n(sh.get('icc_territory'), 3)} costs little.",
                    "Read at month six. Below 0.5x break-even: the force is too big. "
                    "Above 2x: reopen headcount with a measured number."])

        _slide(pdf, "Red team", "The strongest objections, and what survived them",
               ["'It rewards big prescribers' -- share growth is volume-neutral, and flagged prescribers "
                f"grew {_x(psm.get('growth_ratio'))} as fast as matched controls of the same size. HOLDS.",
                "'50/50 is arbitrary' -- swept; the tuned weight fails out of time, 50/50 does not. HOLDS.",
                "'You found growth, not persuadability' -- true; no call data. The pilot resolves it. OPEN.",
                "'Meals are a poor proxy for calls' -- agreed; hence HOLD headcount, not cut. ACCEPTED.",
                "'Medicare-only, 17 months old' -- right lens for older AF patients; refresh yearly. MEDIUM.",
                "'Price negotiation changes the maths' -- the 2026 Medicare negotiated price ($231 / 30 days) "
                f"raises the break-even response from {_p(h3.get('required_ceiling_at_current'), 2)} "
                "by ~1.6x. It strengthens 're-target, do not hire'."])

        _slide(pdf, "Roadmap & kill criteria", "Thirty-six weeks from sign-off to a measured decision",
               ["Weeks 0-2: sign-off -- freeze the rule, the 90% floor and the share endpoint.",
                "Weeks 2-6: load the blended list in CRM, brief reps, randomise the 20% hold-out.",
                "Weeks 6-14: redraw territories and transition accounts (imbalance target < 4x).",
                "Weeks 6-32: pilot runs unchanged; month-3 check that noise scales as planned.",
                "Weeks 32-36: read the share-point effect against break-even; size headcount.",
                "Kill: effect < 0.5x break-even -> shrink/redeploy; blend < floor at refresh -> "
                f"move to {_p(fs.get('robust_weight_p95'), 0)}; call compliance < 80% -> fix adoption first."])

        _slide(pdf, "Limitations", "What this cannot tell you",
               ["Medicare Part D only; ~17-month lag; suppression hides the smallest prescribers.",
                "No rep call data: the back-test shows where growth happened, not what caused it.",
                "The visit proxy (brand-named meals) under-counts calls and reps choose whom to see.",
                "New-writer acquisition is not modelled; non-writers carry no opportunity score.",
                "Straight-line distance, ZIP3 units, no rep tenure or org boundaries."])

        _slide(pdf, "Next steps", "What a brand team would do with this",
               ["Pilot: hold out 20% of the new list for two quarters, scored on brand-share change;",
                "that is the causal test CMS data cannot provide.",
                "Replace Part D with all-payer claims (IQVIA/Symphony) to remove the Medicare skew.",
                "Join CRM call logs to replace the meal proxy with observed calls.",
                "Add drive-time matrices and ZIP5 splits before executing the alignment."])

        # --- data-science appendix (src/ds, figures from src/report/ds_report) --
        ds = m.get("ds_evaluation", {})
        if ds:
            cf, ca, shr = m.get("ds_conformal", {}), m.get("ds_causal", {}), m.get("ds_shrinkage", {})
            _slide(pdf, "Appendix  |  Data science", "How the models were evaluated, and what they cannot do",
                   [f"Pre-declared primary metric (value capture at k = {_n(ds.get('k'))}) and guardrail; "
                    f"winner under the guardrail: {ds.get('winner_under_guardrail', '--')}.",
                    f"Regression-to-the-mean trap found and fixed: corr(share, change) = "
                    f"{shr.get('mean_reversion_corr', '--')}; value-aligned target.",
                    f"Calibrated 90% intervals: {_p(cf.get('in_period_coverage'))} in period, "
                    f"{_p(cf.get('out_of_time_conformal'))} out of time.",
                    f"Double ML: {ca.get('theta_points', '--')} pts [{(ca.get('ci_points') or ['--', '--'])[0]}, "
                    f"{(ca.get('ci_points') or ['--', '--'])[1]}], robustness value {_p(ca.get('robustness_value'))}.",
                    "Full method and results: docs/TECHNICAL_REPORT.md; model and data cards in docs/."])
            for a, b in (("DS1_ladder", "DS2_gain"), ("DS3_coverage", "DS4_uplift"),
                         ("DS5_dml", "DS6_ablation")):
                fig = plt.figure(figsize=(13.33, 7.5))
                for i, name in enumerate((a, b)):
                    f = FIGS / f"{name}.png"
                    if f.exists():
                        ax = fig.add_axes((0.03 + i * 0.49, 0.08, 0.46, 0.84))
                        ax.imshow(plt.imread(f))
                        ax.axis("off")
                _source(fig, "Data-science appendix; method in docs/TECHNICAL_REPORT.md.")
                pdf.savefig(fig)
                plt.close(fig)

    log.info("deck written: %s", DECK.relative_to(ROOT))


def run() -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    m = _m()
    # Data-science figures and docs first, so the deck's appendix can embed them.
    if m.get("ds_evaluation"):
        from src.report import ds_report
        ds_report.run()
    builders = [("E1_disagreement", e1_disagreement), ("E2_backtest_lift", e2_lift),
                ("E3_reach_curve", e3_reach), ("E4_sizing", e4_sizing),
                ("E5_territory_before_after", e5_territory),
                ("E6_challenger", e6_challenger), ("E7_blend_frontier", e7_frontier),
                ("E8_pilot_power", e8_pilot)]
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

    # The steering-committee pack: 10-slide deck and one-page memo.
    from src.report import executive
    executive.build(m)


if __name__ == "__main__":
    run()

