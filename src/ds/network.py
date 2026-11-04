"""Group-practice peer effects: do prescribers move with their practice?

    python -m src.ds.network

DATA. CMS Doctors and Clinicians National Downloadable File (public, ~900 MB):
each clinician's NPI and the PAC ID of every group practice they bill through.
Streamed with DuckDB into (npi, practice) pairs -- the CSV never enters pandas.
CAVEAT: the file is a current enrolment snapshot applied to 2022-2024
prescribing, so a doctor who moved practice is mis-assigned; that biases peer
effects TOWARDS zero, not away from it.

THREE QUESTIONS
    1. Does brand share cluster within practices? Intraclass correlation of
       shrunk share across practices, against a permutation null (prescribers
       shuffled across practices of the same size).
    2. Do peers carry predictive information? Leave-one-out peer features --
       practice-mates' shrunk share and their prior-year change -- added to the
       value model, scored on the same out-of-time holdout and k.
    3. What does it imply for targeting? Practice-mates of the recommended list
       who are not on it: the reach a practice-level call could add if peer
       influence is real (a hypothesis the pilot can test by randomising at the
       practice, not the prescriber, level).
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from src.config import ROOT, path
from src.ds import features as F
from src.ds.data import n_budget
from src.ds.evaluation import metrics_at_k
from src.ds.shrinkage import prepared
from src.ds.tracking import log_run
from src.models.opportunity import hybrid_score
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

DAC = ROOT / "dataset" / "dac" / "DAC_NationalDownloadableFile.csv"
LINKS = "practice_links.parquet"
MAX_PRACTICE = 500          # beyond this a "practice" is a health system, not a peer group
N_PERM = 20


def extract_links() -> pd.DataFrame:
    """(npi, practice) pairs from the CMS file, streamed through DuckDB."""
    out = path("processed") / LINKS
    if out.exists() and out.stat().st_mtime > DAC.stat().st_mtime:
        return pd.read_parquet(out)
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='600MB'; SET threads=2")
        con.execute(f"""
            COPY (
              SELECT DISTINCT TRY_CAST("NPI" AS BIGINT) AS npi,
                     TRY_CAST(org_pac_id AS BIGINT) AS practice,
                     TRY_CAST(num_org_mem AS INTEGER) AS practice_members
              FROM read_csv('{DAC.as_posix()}', header=true, all_varchar=true,
                            ignore_errors=true, parallel=false)
              WHERE org_pac_id IS NOT NULL AND org_pac_id <> ''
            ) TO '{out.as_posix()}' (FORMAT PARQUET)""")
    finally:
        con.close()
    df = pd.read_parquet(out)
    log.info("practice links: %s (npi, practice) pairs from %s", f"{len(df):,}", DAC.name)
    return df


def practice_table(links: pd.DataFrame, npis: pd.Series) -> pd.DataFrame:
    """Memberships of in-market prescribers in practices of a usable size."""
    m = links[links["npi"].isin(npis)].dropna(subset=["practice"])
    size = m.groupby("practice")["npi"].transform("nunique")
    return m[(size >= 2) & (size <= MAX_PRACTICE)][["npi", "practice"]].drop_duplicates()


def loo_peer(members: pd.DataFrame, values: pd.Series, name: str) -> pd.Series:
    """Leave-one-out practice mean of `values`, averaged over a prescriber's practices."""
    d = members.merge(values.rename("v").reset_index(), on="npi", how="inner")
    g = d.groupby("practice")["v"].agg(["sum", "count"])
    d = d.join(g, on="practice")
    d = d[d["count"] >= 2]
    d["loo"] = (d["sum"] - d["v"]) / (d["count"] - 1)
    return d.groupby("npi")["loo"].mean().rename(name)


def icc(members: pd.DataFrame, values: pd.Series) -> float:
    d = members.merge(values.rename("v").reset_index(), on="npi").drop_duplicates("npi")
    k = d.groupby("practice")["v"].agg(["mean", "count", "var"])
    k = k[k["count"] >= 2]
    n_i = k["count"].to_numpy(dtype=float)
    N, a = n_i.sum(), len(n_i)
    grand = np.average(k["mean"], weights=n_i)
    msb = (n_i * (k["mean"] - grand) ** 2).sum() / (a - 1)
    msw = ((n_i - 1) * k["var"].fillna(0)).sum() / (N - a)
    n0 = (N - (n_i ** 2).sum() / N) / (a - 1)
    return float((msb - msw) / (msb + (n0 - 1) * msw))


def run() -> dict:
    links = extract_links()
    train, apply_, _ = prepared()
    for frame in (train, apply_):
        frame["eb_share_fills"] = frame["eb_growth_share"] * frame["class_fills"].clip(lower=0)
    members = practice_table(links, apply_["npi"])
    covered = apply_["npi"].isin(members["npi"])

    # 1. Clustering of shrunk share within practices, vs a permutation null.
    share = apply_.set_index("npi")["eb_share"]
    observed = icc(members, share)
    rng = np.random.default_rng(0)
    null = []
    for _ in range(N_PERM):
        shuffled = pd.Series(rng.permutation(share.to_numpy()), index=share.index)
        null.append(icc(members, shuffled))
    null_hi = float(np.percentile(null, 97.5))

    # 2. Peer features: practice-mates' share now and their change last year.
    def peers(frame: pd.DataFrame, prior_col: str) -> pd.DataFrame:
        s = frame.set_index("npi")
        out = pd.concat([
            loo_peer(members, s["eb_share"], "peer_share"),
            loo_peer(members, s[prior_col].fillna(0), "peer_prior_change"),
            members.groupby("npi")["practice"].nunique().rename("n_practices"),
        ], axis=1)
        return frame.merge(out, left_on="npi", right_index=True, how="left")

    train_p = peers(train, "growth_share")                 # peers' change 2022->23 (contemporaneous for train)
    apply_p = peers(apply_, "prior_growth_share")          # peers' change 2022->23 (strictly prior)
    extra = ["peer_share", "peer_prior_change", "has_peers"]
    for d in (train_p, apply_p):
        d["has_peers"] = d["peer_share"].notna().astype(float)
        d["peer_share"] = d["peer_share"].fillna(d["eb_share"])
        d["peer_prior_change"] = d["peer_prior_change"].fillna(0.0)

    Xtr, enc, _ = F.design(train_p)
    Xap, _, _ = F.design(apply_p, enc)
    Xtr_p, enc_p, _ = F.design(train_p, extra=extra)
    Xap_p, _, _ = F.design(apply_p, enc_p, extra=extra)
    y = train_p["eb_share_fills"].to_numpy(dtype=float)
    base = F.gbm().fit(Xtr, y).predict(Xap)
    with_peers = F.gbm().fit(Xtr_p, y).predict(Xap_p)
    k = n_budget()
    m0, m1 = metrics_at_k(base, apply_p, k), metrics_at_k(with_peers, apply_p, k)

    # 3. Reach: practice-mates of the hybrid list who are not on it.
    score = hybrid_score(apply_).to_numpy(dtype=float)
    listed = set(apply_["npi"].to_numpy()[np.argsort(-score)[:k]])
    mem_list = members[members["npi"].isin(listed)]
    mates = members[members["practice"].isin(mem_list["practice"])]
    unlisted_mates = set(mates["npi"]) - listed
    v = apply_.set_index("npi")["eb_share_fills"].clip(lower=0)

    proc = path("processed")
    summary = pd.DataFrame([
        {"model": "value model", **m0},
        {"model": "value model + practice peers", **m1},
    ])
    write_parquet(summary, proc / "ds_network.parquet")
    res = {
        "source": "CMS Doctors and Clinicians National Downloadable File",
        "links": int(len(links)),
        "in_market_with_practice": int(covered.sum()),
        "coverage": round(float(covered.mean()), 4),
        "practices_used": int(members["practice"].nunique()),
        "icc_shrunk_share": round(observed, 4),
        "icc_permutation_null_97_5": round(null_hi, 4),
        "clusters_beyond_chance": bool(observed > null_hi),
        "value_capture_base": round(m0["value_capture"], 4),
        "value_capture_with_peers": round(m1["value_capture"], 4),
        "ndcg_base": round(m0["ndcg_at_k"], 4),
        "ndcg_with_peers": round(m1["ndcg_at_k"], 4),
        "listed_with_practice": int(mem_list["npi"].nunique()),
        "unlisted_practice_mates": int(len(unlisted_mates)),
        "unlisted_mates_value_share": round(float(v.reindex(list(unlisted_mates)).fillna(0).sum() / v.sum()), 4),
        "caveat": "current enrolment snapshot applied to 2022-2024 behaviour; biases peer effects toward zero",
    }
    log.info("NETWORK: %.0f%% of in-market prescribers matched to %s practices. Shrunk-share "
             "ICC within practice %.3f vs permutation null %.3f (clusters beyond chance: %s).",
             100 * res["coverage"], f"{res['practices_used']:,}", observed, null_hi,
             res["clusters_beyond_chance"])
    log.info("  peer features: value capture %.1f%% -> %.1f%%, NDCG %.3f -> %.3f.",
             100 * m0["value_capture"], 100 * m1["value_capture"], m0["ndcg_at_k"], m1["ndcg_at_k"])
    log.info("  %s unlisted practice-mates of the recommended list hold %.1f%% of share-driven value.",
             f"{len(unlisted_mates):,}", 100 * res["unlisted_mates_value_share"])
    record("ds_network", **res)
    log_run("ds_network", params={"max_practice": MAX_PRACTICE, "k": k},
            metrics={k_: v_ for k_, v_ in res.items() if isinstance(v_, (int, float))},
            artifacts=[proc / "ds_network.parquet"])
    return res


if __name__ == "__main__":
    run()
