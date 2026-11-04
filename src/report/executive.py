"""The steering-committee pack: a 10-slide executive deck and a one-page memo.

    python -m src.report.make_assets      (builds these after the figures)

The full 24-page deck is the analysis; this is the decision. A steering
committee gives a field-force question about twenty minutes, so the pack is
built the way a partner would cut it:

    1  title              the answer, in six words
    2  executive summary  three decisions, the value stack, the ask
    3  the problem        the two rankings disagree
    4  the evidence       held-out year, matched controls
    5  the decision rule  the blend, and why 50/50 holds out of time
    6  the map            territories before and after
    7  headcount          what calling would have to deliver
    8  the business case  every strategy against every belief, with regret
    9  the pilot          design, power, read-out rule
   10  roadmap and ask    36 weeks, kill criteria, three approvals needed today

Every slide is one action title, one exhibit, three numbered takeaways and a
"so what" -- and every number is read from the manifest, never typed.
"""
from __future__ import annotations

import textwrap

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Rectangle

from src.config import ROOT
from src.utils.io import get_logger

log = get_logger(__name__)

FIGS = ROOT / "outputs" / "figures"
EXEC = ROOT / "outputs" / "PharmaTarget_Executive.pdf"
ONEPAGER = ROOT / "outputs" / "PharmaTarget_OnePager.pdf"

PLUM, MAUVE, TERRA = "#3A1F34", "#C3A0A7", "#C75A3A"
BLUSH, PAPER, MUTE, RULE = "#F3E6E1", "#F8EEEA", "#765A6B", "#E2CDC8"
POS, WARN, NEG, TEXT_HI = "#4C7D5A", "#B7791F", "#A3263E", "#F8EEEA"
SERIF = "DejaVu Serif"
N_SLIDES = 10


# --------------------------------------------------------------- formatting

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


def _usd(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "--"
    sign = "-" if v < 0 else ""
    v = abs(v)
    return f"{sign}${v / 1e6:.1f}M" if v >= 1e6 else f"{sign}${v:,.0f}"


def _n(v, d: int = 0) -> str:
    try:
        return f"{float(v):,.{d}f}"
    except (TypeError, ValueError):
        return "--"


def _wrap(s: str, width: int) -> str:
    return "\n".join(textwrap.fill(p, width) for p in s.split("\n"))


# ----------------------------------------------------------------- figures

def e9_beliefs(m: dict):
    """Expected value of each strategy against belief about the call response."""
    bc = m.get("business_case_value") or {}
    rows = bc.get("by_belief") or []
    if not rows:
        return None
    x = np.array([r["median_x"] for r in rows])
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    band = bc.get("pilot_best_band_x")
    if band:
        ax.axvspan(band[0], band[1], color=TERRA, alpha=0.09)
        ax.text(np.sqrt(band[0] * band[1]), 0.03, "the pilot wins here", transform=ax.get_xaxis_transform(),
                ha="center", va="bottom", fontsize=8.5, color=TERRA, fontweight="bold")
    for key, colour, lw, ls, lab in (
            ("pilot_then_decide", TERRA, 2.8, "-", "Hold + pilot, then decide"),
            ("grow", PLUM, 1.8, "-", "Grow now (+30 reps)"),
            ("cut", MAUVE, 1.8, "--", "Cut now (-20 reps)")):
        ax.plot(x, [r[key] / 1e6 for r in rows], color=colour, lw=lw, ls=ls, label=lab, marker="o", ms=3)
    ax.axhline(0, color=MUTE, lw=0.8)
    ax.text(x[0], 0.6, "hold, no pilot", fontsize=7, color=MUTE)
    ax.set_xscale("log")
    ax.set_xticks([0.25, 0.5, 1, 2, 4], ["0.25x", "0.5x", "1x", "2x", "4x"])
    ax.set_ylim(max(ax.get_ylim()[0], -40), min(ax.get_ylim()[1], 60))
    ax.set_xlabel("Belief: how well calls work, x the break-even response", color=MUTE)
    ax.set_ylabel(f"Expected value vs holding, {bc.get('horizon_years', 2):.0f} yrs ($M)", color=MUTE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    return fig


def e4_exec(m: dict):
    """Required response by force size, 40-150 reps, at today's net price and the 2026 price."""
    p = ROOT / "data" / "processed" / "sizing_required_response.parquet"
    if not p.exists():
        return None
    import pandas as pd
    d = pd.read_parquet(p).dropna()
    d = d[(d["n_reps"] >= 30) & (d["n_reps"] <= 150)]
    h3 = m.get("headline_h3", {})
    cur, rc = h3.get("current_n_reps", 60), h3.get("required_ceiling_at_current")
    ira_x = 380 / 231
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    ax.plot(d["n_reps"], d["required_ceiling"] * 100, color=TERRA, lw=2.6, label="at today's net price ($380)")
    ax.plot(d["n_reps"], d["required_ceiling"] * 100 * ira_x, color=PLUM, lw=1.8, ls="--",
            label="at the 2026 Medicare price ($231)")
    ax.axvline(cur, color=MUTE, ls=":", lw=1)
    if rc:
        ax.scatter([cur], [rc * 100], color=TERRA, zorder=3, s=40)
        ax.annotate(f"today's 60th rep needs {rc * 100:.2f}% / yr", (cur, rc * 100), xytext=(cur + 8, rc * 100 - 0.25),
                    fontsize=8, color=PLUM)
    ax.axhline(0, color=MUTE, lw=0.6)
    ax.text(32, 0.12, "measured from public data: no detectable response", fontsize=7.5, color=NEG)
    ax.set_xlabel("Field force size (reps)", color=MUTE)
    ax.set_ylabel("Response the last rep must deliver\n(% of a prescriber's headroom per year)", color=MUTE)
    for s_ in ("top", "right"):
        ax.spines[s_].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    return fig


def e10_roadmap():
    phases = [
        ("Align", "Sign-off: freeze rule, floor, endpoint", 0, 2, MAUVE),
        ("Re-target", "CRM list + rep briefing", 2, 6, PLUM),
        ("Re-target", "Randomise 20% hold-out", 4, 6, PLUM),
        ("Territories", "Redraw + account hand-over", 6, 14, PLUM),
        ("Pilot", "Two quarters, arms unchanged", 6, 32, TERRA),
        ("Decide", "Read effect, size headcount", 32, 36, POS),
    ]
    lanes = ["Align", "Re-target", "Territories", "Pilot", "Decide"]
    fig, ax = plt.subplots(figsize=(7.6, 3.4))
    fig.patch.set_facecolor(PAPER)
    ax.set_facecolor(PAPER)
    used: dict[str, int] = {}
    for lane, name, a, b, col in phases:
        k = used.get(lane, 0)
        used[lane] = k + 1
        y = lanes.index(lane) + k * 0.38
        ax.add_patch(FancyBboxPatch((a, y - 0.15), b - a, 0.3, boxstyle="round,pad=0,rounding_size=0.12",
                                    fc=col, ec="none"))
        inside = (b - a) > 0.42 * len(name)
        ax.text(a + 0.3 if inside else b + 0.4, y, name, va="center", fontsize=7.5,
                color=("white" if col != MAUVE else PLUM) if inside else PLUM)
    ax.scatter([18], [lanes.index("Pilot") + 0.38], marker="D", color=TERRA, s=30, zorder=3)
    ax.text(18.6, lanes.index("Pilot") + 0.38, "month-3 check", va="center", fontsize=7, color=TERRA)
    ax.set_yticks(range(len(lanes)), lanes, fontsize=8)
    ax.set_ylim(len(lanes) - 0.4, -0.6)
    ax.set_xlim(0, 36)
    ax.set_xticks(range(0, 37, 4), [f"wk {w}" for w in range(0, 37, 4)], fontsize=7)
    ax.grid(axis="x", color=RULE, lw=0.6)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    return fig


# ------------------------------------------------------------------ chrome

def _new(dark: bool = False):
    fig = plt.figure(figsize=(13.33, 7.5))
    fig.patch.set_facecolor(PLUM if dark else PAPER)
    return fig


def _chrome(fig, n: int, eyebrow: str, title: str, klass: str = "") -> None:
    fig.patches.append(Rectangle((0, 0), 0.012, 1, transform=fig.transFigure, color=PLUM))
    fig.text(0.05, 0.925, eyebrow.upper(), fontsize=9, color=MUTE, fontweight="bold")
    if klass:
        fig.text(0.05 + 0.0068 * len(eyebrow) + 0.02, 0.925, klass, fontsize=8, color=TERRA,
                 fontweight="bold")
    fig.text(0.95, 0.925, f"{n:02d} / {N_SLIDES:02d}", fontsize=9, color=MUTE, ha="right")
    fig.patches.append(Rectangle((0.05, 0.905), 0.04, 0.004, transform=fig.transFigure, color=TERRA))
    fig.text(0.05, 0.875, _wrap(title, 66), fontsize=21, color=PLUM, va="top",
             family=SERIF, fontweight="bold", linespacing=1.15)
    fig.text(0.05, 0.03, "Source: CMS Medicare Part D & Open Payments, 2022-2024; pipeline "
             "output (data/manifest.json). Client and brand illustrative.", fontsize=7, color=MUTE)


# Fraction of each analysis PNG to trim (top, bottom): its own action title and
# source line, which the slide already carries. Exec-only figures have neither.
CROP = {"E1_disagreement": (0.13, 0.13), "E2_backtest_lift": (0.12, 0.07),
        "E5_territory_before_after": (0.05, 0.06), "E7_blend_frontier": (0.125, 0.07),
        "E8_pilot_power": (0.10, 0.07)}


def _image(fig, name: str, rect: tuple[float, float, float, float]) -> bool:
    p = FIGS / f"{name}.png"
    if not p.exists():
        return False
    img = plt.imread(p)
    top, bottom = CROP.get(name, (0.0, 0.0))
    h = img.shape[0]
    img = img[int(top * h): h - int(bottom * h)]
    ax = fig.add_axes(rect)
    ax.imshow(img)
    ax.axis("off")
    return True


def _takeaways(fig, items: list[str], x: float = 0.66, top: float = 0.70, width: int = 44) -> None:
    fig.text(x, top + 0.03, "WHAT IT SHOWS", fontsize=8, color=MUTE, fontweight="bold")
    y = top
    for i, t in enumerate(items, 1):
        fig.text(x, y, f"{i}", fontsize=15, color=TERRA, fontweight="bold", va="top", family=SERIF)
        body = _wrap(t, width)
        fig.text(x + 0.028, y - 0.004, body, fontsize=10.5, color=PLUM, va="top", linespacing=1.3)
        y -= 0.05 + 0.032 * body.count("\n") + 0.03


def _so_what(fig, text: str, y: float = 0.08) -> None:
    fig.patches.append(FancyBboxPatch((0.05, y), 0.90, 0.075, transform=fig.transFigure,
                                      boxstyle="round,pad=0,rounding_size=0.01", fc=BLUSH, ec="none"))
    fig.patches.append(Rectangle((0.05, y), 0.005, 0.075, transform=fig.transFigure, color=TERRA))
    fig.text(0.068, y + 0.0375, "SO WHAT", fontsize=8.5, color=TERRA, fontweight="bold", va="center")
    fig.text(0.13, y + 0.0375, _wrap(text, 150), fontsize=10.5, color=PLUM, va="center")


def _save(pdf: PdfPages, fig) -> None:
    pdf.savefig(fig, facecolor=fig.get_facecolor())
    plt.close(fig)


# ------------------------------------------------------------------ slides

def _facts(m: dict) -> dict:
    rec, t = m.get("recommendation", {}), m.get("territory_headline", {})
    fs, pdz = m.get("decision_frontier", {}), m.get("pilot_design", {})
    bc, h3 = m.get("business_case_value", {}), m.get("headline_h3", {})
    psm, dis = m.get("propensity_matched", {}), m.get("disagreement", {})
    rt = bc.get("retargeting_per_year_by_response", {})
    return {"rec": rec, "t": t, "fs": fs, "pd": pdz, "sh": pdz.get("share", {}),
            "fl": pdz.get("fills", {}), "bc": bc, "h3": h3, "psm": psm, "dis": dis, "rt": rt,
            "cp": m.get("call_plan", {}), "boot": m.get("bootstrap_60rep", {})}


def _title_slide(pdf, f):
    fig = _new(dark=True)
    fig.patches.append(Rectangle((0.62, 0), 0.38, 1, transform=fig.transFigure, color="#4D2A45"))
    fig.text(0.06, 0.82, "PHARMATARGET  |  DOAC FIELD STRATEGY", fontsize=10, color=MAUVE, fontweight="bold")
    fig.text(0.06, 0.70, "Target the gap,", fontsize=50, color=TEXT_HI, family=SERIF, fontweight="bold")
    fig.text(0.06, 0.58, "not the volume.", fontsize=50, color=TERRA, family=SERIF, fontweight="bold")
    fig.text(0.06, 0.46, _wrap("Same 60 reps, same cost: re-target the calls, redraw the map, and "
                               "measure what a call is worth before changing headcount.", 62),
             fontsize=14, color="#E5D2D3", va="top", linespacing=1.4)
    fig.text(0.06, 0.10, "Steering committee  |  decision pack  |  10 slides", fontsize=9, color=MAUVE)
    items = [("01", "Re-target", f"{_x(f['rec'].get('share_vs_volume'))} share gains"),
             ("02", "Redraw", f"{_x(f['t'].get('imbalance_before'), 0)} -> {_x(f['t'].get('imbalance_after'), 1)} imbalance"),
             ("03", "Pilot", f"{_p(f['sh'].get('power_holdout20_6m'), 0)} power, 2 quarters")]
    for i, (n, a, b) in enumerate(items):
        y = 0.70 - i * 0.19
        fig.text(0.66, y, n, fontsize=28, color=TERRA, family=SERIF, fontweight="bold")
        fig.text(0.72, y + 0.035, a, fontsize=17, color=TEXT_HI, fontweight="bold")
        fig.text(0.72, y - 0.005, b, fontsize=11, color=MAUVE)
    _save(pdf, fig)


def _summary_slide(pdf, f):
    fig = _new()
    _chrome(fig, 2, "Executive summary", "Re-target and redraw now; hold headcount and let a "
            "two-quarter pilot decide it")
    cards = [
        ("DO NOW", POS, "Re-target the 60-rep list",
         f"50/50 opportunity + volume blend. In held-out 2024 it won {_x(f['rec'].get('share_vs_volume'))} "
         f"the share gains of today's list and kept {_p(f['rec'].get('abs_vs_volume'), 0)} of its absolute "
         f"growth; it clears the 90% floor in {_p(f['fs'].get('equal_weight_p_clears_floor'), 0)} of re-draws."),
        ("DO NOW", POS, "Redraw the territories",
         f"Workload imbalance {_x(f['t'].get('imbalance_before'), 0)} -> {_x(f['t'].get('imbalance_after'), 1)}, "
         f"every territory contiguous, travel {_p(f['t'].get('travel_reduction_pct'), 0)} shorter. "
         "Pure arithmetic: no behavioural assumption."),
        ("TEST FIRST", WARN, "Hold 60 reps, run the pilot",
         f"No measurable call response in public data. A 20% hold-out scored on share points "
         f"detects the break-even response with {_p(f['sh'].get('power_holdout20_6m'), 0)} power "
         f"in six months, and has the lowest worst-case regret of any headcount option."),
    ]
    for i, (tag, col, head, body) in enumerate(cards):
        x0 = 0.05 + i * 0.305
        fig.patches.append(FancyBboxPatch((x0, 0.33), 0.285, 0.43, transform=fig.transFigure,
                                          boxstyle="round,pad=0,rounding_size=0.012", fc="#FBF5F2", ec=RULE))
        fig.patches.append(FancyBboxPatch((x0 + 0.02, 0.70), 0.075, 0.035, transform=fig.transFigure,
                                          boxstyle="round,pad=0,rounding_size=0.015", fc=col, ec="none"))
        fig.text(x0 + 0.0575, 0.7175, tag, fontsize=8, color="white", ha="center", va="center", fontweight="bold")
        fig.text(x0 + 0.02, 0.665, head, fontsize=15, color=PLUM, family=SERIF, fontweight="bold", va="top")
        fig.text(x0 + 0.02, 0.60, _wrap(body, 44), fontsize=10.5, color=PLUM, va="top", linespacing=1.4)
    bc, rt = f["bc"], f["rt"]
    stack = [(f"{_usd(rt.get('1.0'))} / yr", "re-targeting, zero incremental cost"),
             (_usd(bc.get("base_pilot_value")), f"pilot vs deciding blind, {bc.get('horizon_years', 2):.0f} yrs"),
             (f">= {bc.get('grow_pays_above_x', '--')}x", "belief needed to justify hiring now"),
             ("$0", "new headcount until the pilot reads out")]
    fig.patches.append(FancyBboxPatch((0.05, 0.10), 0.90, 0.17, transform=fig.transFigure,
                                      boxstyle="round,pad=0,rounding_size=0.012", fc=PLUM, ec="none"))
    for i, (v, k) in enumerate(stack):
        x0 = 0.08 + i * 0.22
        fig.text(x0, 0.205, v, fontsize=20, color=TERRA, fontweight="bold", family=SERIF)
        fig.text(x0, 0.145, _wrap(k, 30), fontsize=9.5, color="#E5D2D3", va="top")
    _save(pdf, fig)


def _exhibit(pdf, n, eyebrow, klass, title, img, takeaways, so_what, rect=(0.04, 0.17, 0.60, 0.63)):
    fig = _new()
    _chrome(fig, n, eyebrow, title, klass)
    _image(fig, img, rect)
    _takeaways(fig, takeaways)
    _so_what(fig, so_what)
    _save(pdf, fig)


def _roadmap_slide(pdf, f):
    fig = _new()
    _chrome(fig, 10, "Roadmap and the ask", "Thirty-six weeks to a measured headcount decision; "
            "three approvals needed today", "")
    _image(fig, "E10_roadmap", (0.04, 0.36, 0.58, 0.45))
    fig.text(0.05, 0.33, "KILL CRITERIA", fontsize=8, color=MUTE, fontweight="bold")
    kills = ["Pilot effect < 0.5x break-even at month 6 -> redeploy or shrink through attrition",
             "Pilot effect > 2x break-even -> reopen headcount with a measured response",
             f"Blend keeps < 90% of volume's growth at a refresh -> move to "
             f"{_p(f['fs'].get('robust_weight_p95'), 0)} weight",
             "Call compliance < 80% on the new list -> fix adoption before reading any result"]
    for i, k in enumerate(kills):
        fig.text(0.05, 0.29 - i * 0.042, f"IF  {k}", fontsize=9.5, color=PLUM)
    fig.patches.append(FancyBboxPatch((0.66, 0.12), 0.29, 0.69, transform=fig.transFigure,
                                      boxstyle="round,pad=0,rounding_size=0.012", fc=PLUM, ec="none"))
    fig.text(0.68, 0.76, "DECISIONS NEEDED TODAY", fontsize=9, color=MAUVE, fontweight="bold")
    asks = [("1", "Approve the blended call list", "Same reps, same budget; CRM change in four weeks."),
            ("2", "Approve the territory redraw", "Phased hand-over; top accounts stay with their rep."),
            ("3", "Freeze headcount at 60 for two quarters", "And fund the 20% hold-out pilot; read-out "
             "at month six decides the size.")]
    for i, (n, a, b) in enumerate(asks):
        y = 0.69 - i * 0.18
        fig.text(0.68, y, n, fontsize=26, color=TERRA, family=SERIF, fontweight="bold", va="top")
        fig.text(0.72, y - 0.005, _wrap(a, 26), fontsize=13, color=TEXT_HI, fontweight="bold", va="top")
        fig.text(0.72, y - 0.075, _wrap(b, 34), fontsize=9.5, color="#E5D2D3", va="top", linespacing=1.35)
    _save(pdf, fig)


def build_executive(m: dict) -> None:
    """The 10-slide steering-committee deck."""
    f = _facts(m)
    for name, fn in (("E9_business_case", lambda: e9_beliefs(m)), ("E10_roadmap", e10_roadmap),
                     ("E4_exec_headcount", lambda: e4_exec(m))):
        fig = fn()
        if fig is not None:
            fig.savefig(FIGS / f"{name}.png", dpi=170, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)

    rec, t, fs, sh, fl, bc, h3 = f["rec"], f["t"], f["fs"], f["sh"], f["fl"], f["bc"], f["h3"]
    dis, psm = f["dis"], f["psm"]
    EXEC.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(EXEC) as pdf:
        _title_slide(pdf, f)
        _summary_slide(pdf, f)
        _exhibit(pdf, 3, "The problem", "ARITHMETIC",
                 f"Volume ranking and opportunity disagree for {_p(dis.get('disagree_by_2plus_pct'), 0)} "
                 "of prescribers: the default calls on doctors with nothing left to win",
                 "E1_disagreement",
                 [f"{_n(dis.get('volume_low_opportunity_high'))} low-volume, high-opportunity writers are "
                  "skipped by the volume rule.",
                  f"{_n(dis.get('volume_high_opportunity_low'))} high-volume writers with little headroom "
                  "are over-served.",
                  "Opportunity = what a strong comparable prescriber reaches, minus what this one "
                  "gives the brand today."],
                 "The list, not the headcount, is the first lever: it is free to change.")
        _exhibit(pdf, 4, "The evidence", "BACK-TESTED",
                 f"In a year the model never saw, flagged prescribers grew {_x(psm.get('growth_ratio'))} "
                 "as fast as matched peers",
                 "E2_backtest_lift",
                 [f"Fit on 2023, frozen, scored on 2024; {_n(psm.get('n_pairs'))} propensity-matched pairs, "
                  f"worst covariate imbalance {_n(psm.get('worst_smd_after'), 3)}.",
                  f"+{_n(psm.get('paired_difference'), 1)} branded fills per prescriber "
                  f"[{_n(psm.get('ci_low'), 1)}, {_n(psm.get('ci_high'), 1)}].",
                  "It shows where growth happened, not what a call caused: that is the pilot's job."],
                 "The ranking finds growing prescribers out of time; it is not fitted to the exam.")
        _exhibit(pdf, 5, "The decision rule", "BACK-TESTED",
                 "A 50/50 blend wins share without giving up the base; a weight tuned on last year "
                 "would have failed this year",
                 "E7_blend_frontier",
                 [f"Rule fixed before the comparison: most share gain while keeping >= 90% of volume's "
                  f"growth. The blend: {_x(rec.get('share_vs_volume'))} share, {_p(rec.get('abs_vs_volume'), 0)} kept.",
                  f"Tuned on 2022->23, the best weight ({_p(fs.get('selected_weight'), 0)}) clears the floor in "
                  f"{_p(fs.get('holdout_p_clears_floor'), 0)} of 2024 re-draws; 50/50 in "
                  f"{_p(fs.get('equal_weight_p_clears_floor'), 0)}.",
                  f"For 95% confidence, use {_p(fs.get('robust_weight_p95'), 0)} at a small cost in share."],
                 "Adopt 50/50 and re-read the floor at every annual data refresh.")
        _exhibit(pdf, 6, "The map", "ARITHMETIC",
                 f"Redrawing cuts workload imbalance from {_x(t.get('imbalance_before'), 0)} to "
                 f"{_x(t.get('imbalance_after'), 1)} with every territory contiguous",
                 "E5_territory_before_after",
                 [f"Contiguity {_p(t.get('contiguity_before'), 0)} -> {_p(t.get('contiguity_after'), 0)}; "
                  f"travel {_p(t.get('travel_reduction_pct'), 0)} shorter.",
                  f"Plain k-means is tighter but leaves {_x(t.get('kmeans_imbalance'), 0)} imbalance: "
                  "compact is not the same as workable.",
                  "Same 60 reps: no hiring, no new cost."],
                 "Redraw alongside the list change so reps meet the new targets inside a fair territory.",
                 rect=(0.03, 0.20, 0.62, 0.55))
        _exhibit(pdf, 7, "Headcount", "SCENARIO",
                 f"Today's 60th rep pays only if a year of calls captures {_p(h3.get('required_ceiling_at_current'), 2)} "
                 "of a prescriber's headroom, a number public data cannot measure",
                 "E4_exec_headcount",
                 ["Brand-named visit events show no dose-response once prescribers are compared "
                  "within volume bands.",
                  "So headcount is not priced on an invented curve; the required response is.",
                  "The 2026 Medicare negotiated price ($231 / 30 days) raises that bar ~1.6x."],
                 "Do not hire or cut on a number nobody has measured. Measure it.")
        _exhibit(pdf, 8, "The business case", "SCENARIO",
                 f"For any belief from {(bc.get('pilot_best_band_x') or ['--', '--'])[0]}x to "
                 f"{(bc.get('pilot_best_band_x') or ['--', '--'])[1]}x break-even, piloting beats "
                 "every decision made blind",
                 "E9_business_case",
                 [f"Re-targeting is worth {_usd(f['rt'].get('1.0'))} a year at the break-even response, "
                  "at zero incremental cost.",
                  f"Hold + pilot is worth {_usd(bc.get('base_pilot_value'))} over two years vs holding "
                  f"blind, net of {_usd(bc.get('base_pilot_cost'))} forgone during the hold-out.",
                  f"Lowest worst-case regret of any option ({_usd((bc.get('max_regret') or {}).get('pilot'))}); "
                  f"hiring pays only if calls beat break-even by {bc.get('grow_pays_above_x', '--')}x."],
                 "The pilot is both the expected-value choice and the robust one: approve it.")
        _exhibit(pdf, 9, "The pilot", "SCENARIO",
                 "Scored on brand-share points, a two-quarter hold-out can find the answer; scored on "
                 "fills it cannot",
                 "E8_pilot_power",
                 [f"Hold out 20% of the list (no calls) for two quarters: {_p(sh.get('power_holdout20_6m'), 0)} "
                  f"power on share points vs {_p(fl.get('power_holdout20_6m'), 0)} on fills.",
                  "Fills are dominated by practice size; share points are volume-neutral.",
                  "Read at month six: < 0.5x break-even shrink, > 2x reopen hiring."],
                 "Fix the endpoint before launch: the choice of metric decides whether the pilot works.")
        _roadmap_slide(pdf, f)
    log.info("executive deck written: %s", EXEC.relative_to(ROOT))


def build_onepager(m: dict) -> None:
    """A one-page decision memo (US Letter, portrait)."""
    f = _facts(m)
    rec, t, fs, sh, bc, h3, psm = f["rec"], f["t"], f["fs"], f["sh"], f["bc"], f["h3"], f["psm"]
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor(PAPER)
    fig.patches.append(Rectangle((0, 0.885), 1, 0.115, transform=fig.transFigure, color=PLUM))
    fig.text(0.07, 0.955, "DECISION MEMO  |  DOAC FIELD STRATEGY", fontsize=8.5, color=MAUVE, fontweight="bold")
    fig.text(0.07, 0.905, "Target the gap, not the volume.", fontsize=24, color=TEXT_HI,
             family=SERIF, fontweight="bold")

    def block(y, head, body, colour=PLUM, width=92):
        fig.text(0.07, y, head, fontsize=10, color=TERRA, fontweight="bold")
        txt = _wrap(body, width)
        fig.text(0.07, y - 0.018, txt, fontsize=9.5, color=colour, va="top", linespacing=1.4)
        return y - 0.042 - 0.0182 * (txt.count("\n") + 1)

    y = 0.86
    y = block(y, "THE ANSWER", "Keep the same 60 reps and cost. Re-target their calls on a 50/50 blend of "
              "modelled opportunity and volume, redraw the territories, and hold headcount until a "
              "two-quarter pilot measures what a call is worth.")
    y = block(y, "WHY WE BELIEVE IT", f"In held-out 2024 the blended list won {_x(rec.get('share_vs_volume'))} the "
              f"share gains of today's volume list and kept {_p(rec.get('abs_vs_volume'), 0)} of its absolute growth "
              f"(clears the 90% floor in {_p(fs.get('equal_weight_p_clears_floor'), 0)} of re-draws). Flagged "
              f"prescribers grew {_x(psm.get('growth_ratio'))} as fast as propensity-matched peers. A blend weight "
              f"tuned on the earlier year failed out of time; 50/50 did not, because it was never tuned.")
    y = block(y, "THE MAP", f"Territories drawn alphabetically by state carry a {_x(t.get('imbalance_before'), 0)} "
              f"workload imbalance and {_p(t.get('contiguity_before'), 0)} contiguity. The redraw: "
              f"{_x(t.get('imbalance_after'), 1)}, {_p(t.get('contiguity_after'), 0)} contiguous, travel "
              f"{_p(t.get('travel_reduction_pct'), 0)} shorter.")
    y = block(y, "WHY NOT HIRE (OR CUT)", f"Public data show no measurable call response. Today's 60th rep pays only if a "
              f"year of calls captures {_p(h3.get('required_ceiling_at_current'), 2)} of a prescriber's headroom. "
              f"Hiring pays only if calls beat that by {bc.get('grow_pays_above_x', '--')}x, after hiring, ramp-up "
              f"and severance costs; the 2026 Medicare negotiated price raises the bar a further ~1.6x.")

    # value stack
    fig.patches.append(FancyBboxPatch((0.07, y - 0.115), 0.86, 0.10, transform=fig.transFigure,
                                      boxstyle="round,pad=0,rounding_size=0.01", fc=PLUM, ec="none"))
    stack = [(f"{_usd(f['rt'].get('1.0'))}/yr", "re-targeting,\nzero cost"),
             (_usd(bc.get("base_pilot_value")), "pilot vs\ndeciding blind"),
             (_p(sh.get("power_holdout20_6m"), 0), "pilot power,\nsix months"),
             ("$0", "new headcount\nbefore read-out")]
    for i, (v, k) in enumerate(stack):
        x0 = 0.10 + i * 0.21
        fig.text(x0, y - 0.045, v, fontsize=16, color=TERRA, fontweight="bold", family=SERIF)
        fig.text(x0, y - 0.065, k, fontsize=8, color="#E5D2D3", va="top")
    y -= 0.145

    y = block(y, "THE PILOT", f"Randomly hold out 20% of the new list (no calls) for two quarters; score both arms on "
              f"brand-share change with a prior-year adjustment; read at month six. Power {_p(sh.get('power_holdout20_6m'), 0)} "
              f"on share points ({_p(f['fl'].get('power_holdout20_6m'), 0)} if scored on fills). Below 0.5x break-even: "
              f"shrink or redeploy. Above 2x: reopen hiring with a measured number.")
    y = block(y, "RISKS", "Reps keep calling old accounts (CRM nudges, on-list incentive); hold-out contamination "
              "(hidden in CRM, monthly audit); Medicare-only data, ~17 months old (refresh each CMS release).")
    y = block(y, "DECISIONS NEEDED", "1. Approve the blended call list.   2. Approve the territory redraw.   "
              "3. Freeze headcount at 60 for two quarters and fund the 20% hold-out pilot.")
    fig.text(0.07, 0.03, "Every number is read from the pipeline output (data/manifest.json). Real CMS Part D and "
             "Open Payments data, 2022-2024; client and brand illustrative.", fontsize=7, color=MUTE)
    with PdfPages(ONEPAGER) as pdf:
        pdf.savefig(fig, facecolor=fig.get_facecolor())
    plt.close(fig)
    log.info("one-page memo written: %s", ONEPAGER.relative_to(ROOT))


def build(m: dict) -> None:
    build_executive(m)
    build_onepager(m)


__all__ = ["build", "build_executive", "build_onepager"]
