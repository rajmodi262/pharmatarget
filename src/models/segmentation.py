"""Behavioural segmentation with a stability check.

TWO THINGS THAT MAKE THIS MORE THAN A KMEANS CALL
-------------------------------------------------
1. TRAJECTORY FEATURES, NOT A SNAPSHOT. Clustering on this year's volume and
   share produces groups that mean "big" and "small". Clustering on the CHANGE
   in share across three years produces groups that mean "winning them",
   "losing them", "never had them" -- which is what a brand team can act on.

2. STABILITY, NOT JUST SILHOUETTE. Silhouette rewards tight geometry and will
   happily endorse a k that reshuffles completely on a different sample. Every
   candidate k is refit on 25 bootstrap resamples and scored by mean adjusted
   Rand index against the full-sample labels. A k that is not stable under
   resampling is not a segmentation, it is one partition of one sample.

Final k is chosen on both, with a tie broken toward business interpretability.
That last criterion is a judgement call and is documented as one rather than
dressed up as a metric.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from src.config import params, path
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)

FEATURES = [
    "brand_share",           # where they are now
    "share_delta_recent",    # direction of travel, most recent year
    "share_delta_prior",     # direction of travel, prior year
    "log_class_fills",       # scale
    "class_growth",          # is their whole category growing?
    "log_payments",          # promotional exposure
    "opportunity_pct",       # headroom as a fraction of potential
]

# Business names, assigned by rule from cluster centroids rather than by hand.
# A cluster called "Cluster 3" is worthless in a brand meeting; a rule-based
# namer keeps the labels reproducible when the data is refreshed.
STRATEGIES = {
    "Loyal Advocates": "Protect. Lowest call frequency, highest-value relationships. Watch for erosion.",
    "Rising Switchers": "Accelerate. Share is already moving our way -- add frequency while it is.",
    "Untapped Potential": "Convert. High modelled headroom, low current share. The core growth target.",
    "Generic Anchors": "Challenge. Committed to warfarin or a competitor; needs clinical, not promotional, messaging.",
    "Eroding Base": "Defend. Share is falling. Diagnose before spending -- this is often a formulary problem, not a call problem.",
    "Low-Value Tail": "No-call. Insufficient volume or headroom to justify field cost.",
}


def build_panel(scored: pd.DataFrame, payments: pd.DataFrame) -> pd.DataFrame:
    """Wide, one row per NPI, with share trajectory across all three years."""
    p = params()
    yrs = sorted(p["years"]["all"])
    latest = yrs[-1]

    wide = scored.pivot_table(index="npi", columns="year",
                              values=["brand_share", "class_fills", "opportunity_pct_of_potential"],
                              aggfunc="first")
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    wide = wide.reset_index()

    pay = (payments.groupby("npi")["pay_total"].sum().rename("pay_total").reset_index())
    df = wide.merge(pay, on="npi", how="left")
    df["pay_total"] = df["pay_total"].fillna(0.0)

    df["brand_share"] = df[f"brand_share_{latest}"].fillna(0.0)
    df["share_delta_recent"] = (df[f"brand_share_{yrs[-1]}"] - df[f"brand_share_{yrs[-2]}"]).fillna(0.0)
    df["share_delta_prior"] = (df[f"brand_share_{yrs[-2]}"] - df[f"brand_share_{yrs[0]}"]).fillna(0.0)
    df["log_class_fills"] = np.log1p(df[f"class_fills_{latest}"].fillna(0.0))
    df["class_growth"] = ((df[f"class_fills_{yrs[-1]}"] - df[f"class_fills_{yrs[-2]}"])
                          / df[f"class_fills_{yrs[-2]}"].clip(lower=1.0)).fillna(0.0)
    df["log_payments"] = np.log1p(df["pay_total"])
    df["opportunity_pct"] = df[f"opportunity_pct_of_potential_{latest}"].fillna(0.0)

    # SEGMENT THE ADDRESSABLE MARKET, NOT THE WHOLE PART D FILE.
    #
    # Run on all 1.59M prescribers, the clustering spent 83% of its capacity
    # partitioning people who write NO anticoagulants into near-identical
    # all-zero groups: "Untapped Potential" came back as 64.2% of the universe
    # with a brand share of 0.000006 and log class volume of 0.048. Those are
    # not a behavioural segment, they are the out-of-market population.
    #
    # It also inflated the silhouette to 0.807 -- trivially separable zero
    # clusters make the geometry look excellent while the segmentation says
    # nothing. Same failure the deciling had before it was restricted to
    # in-market prescribers; the fix simply was not propagated here.
    before = len(df)
    df = df[df[f"class_fills_{latest}"].fillna(0) > 0]
    log.info("segmenting the addressable market: %s of %s prescribers write the "
             "class (%.1f%% excluded as out-of-market)",
             f"{len(df):,}", f"{before:,}", 100 * (1 - len(df) / max(before, 1)))

    return df.dropna(subset=FEATURES)


def choose_k(X: np.ndarray) -> pd.DataFrame:
    """Silhouette and bootstrap stability for every candidate k."""
    cfg = params()["segmentation"]
    rng = np.random.default_rng(cfg["random_state"])
    sil_sample = min(5_000, len(X))
    idx_sil = rng.choice(len(X), sil_sample, replace=False)

    rows = []
    for k in cfg["k_candidates"]:
        km = KMeans(n_clusters=k, n_init=10, random_state=cfg["random_state"]).fit(X)
        sil = silhouette_score(X[idx_sil], km.labels_[idx_sil])

        aris = []
        for b in range(cfg["bootstrap_runs"]):
            sub = rng.choice(len(X), int(cfg["bootstrap_frac"] * len(X)), replace=False)
            kb = KMeans(n_clusters=k, n_init=3, random_state=cfg["random_state"] + b).fit(X[sub])
            aris.append(adjusted_rand_score(km.labels_[sub], kb.labels_))

        rows.append({"k": k, "silhouette": round(float(sil), 4),
                     "stability_ari": round(float(np.mean(aris)), 4),
                     "stability_sd": round(float(np.std(aris)), 4),
                     "inertia": float(km.inertia_)})
        log.info("  k=%d: silhouette %.3f, bootstrap ARI %.3f (+/- %.3f)",
                 k, sil, np.mean(aris), np.std(aris))

    df = pd.DataFrame(rows)
    # Rank on both, equally weighted. Neither metric alone is trustworthy here.
    df["combined_rank"] = (df["silhouette"].rank(ascending=False)
                           + df["stability_ari"].rank(ascending=False))
    return df.sort_values("combined_rank")


def name_clusters(profile: pd.DataFrame) -> dict[int, str]:
    """Assign business names from centroid position, by rule.

    Rules are applied in priority order and each name is used once, so the
    output is a stable mapping rather than several clusters claiming the same
    label. Where fewer clusters exist than names, the unused names simply do
    not appear -- that is information, not a failure.
    """
    med_share = profile["brand_share"].median()
    med_opp = profile["opportunity_pct"].median()
    med_vol = profile["log_class_fills"].median()

    scores: dict[int, list[tuple[float, str]]] = {}
    for cid, r in profile.iterrows():
        s = []
        s.append((r["brand_share"] * 2 - abs(r["share_delta_recent"]) * 3, "Loyal Advocates"))
        s.append((r["share_delta_recent"] * 5 + r["share_delta_prior"] * 2, "Rising Switchers"))
        s.append((r["opportunity_pct"] * 3 - r["brand_share"] * 2 + r["log_class_fills"] * 0.2,
                  "Untapped Potential"))
        s.append(((1 - r["brand_share"]) * 2 - abs(r["share_delta_recent"]) * 3, "Generic Anchors"))
        s.append((-r["share_delta_recent"] * 5, "Eroding Base"))
        s.append((-(r["log_class_fills"] - med_vol) * 2 - r["opportunity_pct"], "Low-Value Tail"))
        scores[cid] = sorted(s, reverse=True)

    assigned: dict[int, str] = {}
    taken: set[str] = set()
    # Greedy over the strongest (cluster, name) claim available.
    claims = sorted(((sc, cid, nm) for cid, lst in scores.items() for sc, nm in lst),
                    reverse=True)
    for _sc, cid, nm in claims:
        if cid in assigned or nm in taken:
            continue
        assigned[cid] = nm
        taken.add(nm)
    for cid in profile.index:
        assigned.setdefault(cid, f"Segment {cid}")
    _ = (med_share, med_opp)   # thresholds retained for future rule tuning
    return assigned


def run() -> pd.DataFrame:
    proc = path("processed")
    scored = read_parquet(proc / "hcp_scored.parquet")
    payments = read_parquet(proc / "mart_payments.parquet")

    panel = build_panel(scored, payments)
    log.info("segmentation panel: %d prescribers, %d features", len(panel), len(FEATURES))

    scaler = StandardScaler()
    X = scaler.fit_transform(panel[FEATURES].to_numpy(dtype=float))

    diag = choose_k(X)
    k = int(diag.iloc[0]["k"])
    log.info("selected k=%d (silhouette %.3f, stability ARI %.3f)",
             k, diag.iloc[0]["silhouette"], diag.iloc[0]["stability_ari"])

    km = KMeans(n_clusters=k, n_init=10,
                random_state=params()["segmentation"]["random_state"]).fit(X)
    panel["cluster"] = km.labels_

    profile = panel.groupby("cluster")[FEATURES].mean()
    profile["n_hcps"] = panel.groupby("cluster").size()
    names = name_clusters(profile)
    profile["segment"] = [names[c] for c in profile.index]
    profile["strategy"] = [STRATEGIES.get(names[c], "Review.") for c in profile.index]
    profile["pct_of_universe"] = profile["n_hcps"] / len(panel)

    panel["segment"] = panel["cluster"].map(names)

    for _, r in profile.iterrows():
        log.info("  %-20s n=%6d (%.1f%%)  share=%.2f  d_share=%+.3f  opp=%.2f",
                 r["segment"], int(r["n_hcps"]), 100 * r["pct_of_universe"],
                 r["brand_share"], r["share_delta_recent"], r["opportunity_pct"])

    write_parquet(diag, proc / "segmentation_diagnostics.parquet")
    write_parquet(profile.reset_index(), proc / "segment_profiles.parquet")
    write_parquet(panel[["npi", "cluster", "segment"] + FEATURES],
                  proc / "hcp_segments.parquet")
    record("segmentation", k=k,
           silhouette=float(diag.iloc[0]["silhouette"]),
           stability_ari=float(diag.iloc[0]["stability_ari"]),
           segments=[str(s) for s in profile["segment"]])
    return profile


if __name__ == "__main__":
    run()
