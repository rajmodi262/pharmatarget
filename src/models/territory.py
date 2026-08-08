"""Territory alignment: capacitated clustering with contiguity repair.

THE PROBLEM
-----------
Given per-ZIP3 call workload and a rep capacity, partition the country into
territories that are (a) balanced, (b) compact, and (c) CONTIGUOUS.

Constraint (c) is the one most write-ups skip, and skipping it invalidates the
output. Plain capacitated k-means assigns by distance-to-centroid subject to
capacity, which routinely leaves a rep in Ohio owning three ZIP3s in Indiana --
the Ohio territory filled up, so the nearest available centroid for those units
was two states away. That map looks fine at national zoom and is unimplementable
in the field. No alignment gets executed with detached islands in it.

ALGORITHM
---------
    1. seed        k-means++ on unit centroids, weighted by workload
    2. assign      units in ascending order of distance to their nearest
                   centroid, each to the nearest centroid with residual
                   capacity (greedy; earliest-claim wins)
    3. repair      per territory, find connected components on the adjacency
                   graph; keep the largest, reassign every orphan component to
                   the adjacent territory with residual capacity and the
                   nearest centroid
    4. update      recompute workload-weighted centroids
    5. iterate     2-4 to convergence or max_iterations
    6. polish      boundary swaps that reduce total weighted distance without
                   breaking capacity OR contiguity

Assignment order in step 2 matters. Iterating units in arbitrary order lets a
low-workload unit claim a slot a high-workload neighbour needed, and the result
thrashes. Ascending distance-to-nearest lets the units with the least choice go
first, which is the standard fix for greedy capacitated assignment.

WHAT THIS DELIBERATELY IGNORES
------------------------------
Drive time (straight-line distance is used), rep tenure, existing relationships,
and organisational boundaries. In practice those dominate: no client redraws a
map purely on an optimiser's output. Stated in the README limitations.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import econ, params, path
from src.utils.geo import haversine_miles, knn_adjacency, pairwise_miles
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)


def build_units(planned: pd.DataFrame) -> pd.DataFrame:
    """Aggregate prescriber-level call workload up to ZIP3 units."""
    agg = (planned.groupby("zip3")
           .agg(workload=("calls_per_month", "sum"),
                n_hcps=("npi", "count"),
                n_targets=("is_target", "sum"),
                opportunity=("opportunity", "sum"),
                class_fills=("class_fills", "sum"),
                brand_fills=("brand_fills", "sum"),
                high_decile_hcps=("opportunity_decile", lambda s: int((s >= 8).sum())),
                lat=("lat", "mean"),
                lon=("lon", "mean"),
                state=("state", lambda s: s.mode().iat[0] if len(s.mode()) else None))
           .reset_index().rename(columns={"zip3": "unit"}))
    agg = agg.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    # Units with zero workload still need an owner -- a rep's territory is a
    # partition of geography, not of the target list.
    log.info("units: %d ZIP3s, %.0f total monthly calls, %d with zero workload",
             len(agg), agg["workload"].sum(), int((agg["workload"] == 0).sum()))
    return agg


def capacity_per_rep() -> float:
    return econ("calls_per_rep_per_day") * econ("selling_days_per_month")


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #

def baseline_alignment(units: pd.DataFrame, n_territories: int) -> np.ndarray:
    """Alphabetical-by-state assignment. The honest 'before'.

    This is how territories actually get drawn in the absence of an optimiser:
    by administrative convenience. It respects state lines (so it is often
    contiguous by accident) and ignores workload entirely (so it is badly
    imbalanced), which is exactly the pattern the redesign has to beat.
    """
    order = units.sort_values(["state", "unit"]).index.to_numpy()
    assign = np.empty(len(units), dtype=int)
    per = int(np.ceil(len(units) / n_territories))
    for i, idx in enumerate(order):
        assign[idx] = min(i // per, n_territories - 1)
    return assign


# --------------------------------------------------------------------------- #
# Capacitated k-means
# --------------------------------------------------------------------------- #

def _seed_centroids(units: pd.DataFrame, k: int, rng: np.random.Generator) -> np.ndarray:
    """k-means++ seeding, weighted by workload."""
    coords = units[["lat", "lon"]].to_numpy(dtype=float)
    w = units["workload"].to_numpy(dtype=float)
    w = w + w.mean() * 0.01 + 1e-9          # zero-workload units stay selectable
    w = w / w.sum()

    first = rng.choice(len(coords), p=w)
    centroids = [coords[first]]
    for _ in range(k - 1):
        d = np.min(np.stack([
            haversine_miles(coords[:, 0], coords[:, 1], c[0], c[1]) for c in centroids
        ]), axis=0)
        p = (d ** 2) * w
        p = p / p.sum() if p.sum() > 0 else w
        centroids.append(coords[rng.choice(len(coords), p=p)])
    return np.array(centroids)


def _assign_capacitated(units: pd.DataFrame, centroids: np.ndarray,
                        capacity: float) -> np.ndarray:
    """Greedy nearest-centroid assignment subject to capacity."""
    coords = units[["lat", "lon"]].to_numpy(dtype=float)
    workload = units["workload"].to_numpy(dtype=float)
    dist = pairwise_miles(coords[:, 0], coords[:, 1], centroids[:, 0], centroids[:, 1])

    # Units with the least choice (closest to a single centroid) go first.
    order = np.argsort(dist.min(axis=1))
    used = np.zeros(len(centroids))
    assign = np.full(len(units), -1, dtype=int)

    for i in order:
        for t in np.argsort(dist[i]):
            if used[t] + workload[i] <= capacity:
                assign[i] = t
                used[t] += workload[i]
                break
        else:
            # Every territory is full. Overflow to the nearest one rather than
            # leaving the unit unassigned -- an unowned ZIP3 is not a valid map.
            t = int(np.argmin(dist[i]))
            assign[i] = t
            used[t] += workload[i]
    return assign


def _components(nodes: set[str], edges: set[tuple[str, str]]) -> list[set[str]]:
    """Connected components of the induced subgraph on `nodes`."""
    adj: dict[str, set[str]] = {n: set() for n in nodes}
    for a, b in edges:
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)

    seen: set[str] = set()
    out: list[set[str]] = []
    for n in nodes:
        if n in seen:
            continue
        stack, comp = [n], set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.add(cur)
            stack.extend(adj[cur] - seen)
        out.append(comp)
    return out


def _repair_contiguity(units: pd.DataFrame, assign: np.ndarray,
                       edges: set[tuple[str, str]], centroids: np.ndarray,
                       capacity: float) -> np.ndarray:
    """Reassign orphan components to adjacent territories with room.

    For each territory, the largest connected component (by workload) is the
    body; every other component is an orphan. Each orphan moves to the adjacent
    territory with residual capacity whose centroid is nearest. If no adjacent
    territory has room, the orphan stays -- and the contiguity metric reports
    the shortfall honestly rather than the repair silently failing.
    """
    assign = assign.copy()
    unit_ids = units["unit"].to_numpy()
    idx_of = {u: i for i, u in enumerate(unit_ids)}
    workload = units["workload"].to_numpy(dtype=float)
    coords = units[["lat", "lon"]].to_numpy(dtype=float)

    neighbours: dict[str, set[str]] = {u: set() for u in unit_ids}
    for a, b in edges:
        if a in neighbours and b in neighbours:
            neighbours[a].add(b)
            neighbours[b].add(a)

    for t in range(len(centroids)):
        members = set(unit_ids[assign == t])
        if len(members) <= 1:
            continue
        comps = _components(members, edges)
        if len(comps) <= 1:
            continue

        comps.sort(key=lambda c: sum(workload[idx_of[u]] for u in c), reverse=True)
        for orphan in comps[1:]:
            # Territories touching this orphan, excluding its current owner.
            adjacent = {assign[idx_of[nb]]
                        for u in orphan for nb in neighbours[u]
                        if nb not in orphan}
            adjacent.discard(t)
            if not adjacent:
                continue

            orphan_load = sum(workload[idx_of[u]] for u in orphan)
            loads = {tt: workload[assign == tt].sum() for tt in adjacent}
            feasible = [tt for tt in adjacent if loads[tt] + orphan_load <= capacity]
            pool = feasible or list(adjacent)

            centre = coords[[idx_of[u] for u in orphan]].mean(axis=0)
            best = min(pool, key=lambda tt: haversine_miles(
                centre[0], centre[1], centroids[tt][0], centroids[tt][1]))
            for u in orphan:
                assign[idx_of[u]] = best
    return assign


def _update_centroids(units: pd.DataFrame, assign: np.ndarray, k: int,
                      previous: np.ndarray) -> np.ndarray:
    coords = units[["lat", "lon"]].to_numpy(dtype=float)
    w = units["workload"].to_numpy(dtype=float) + 1e-9
    out = previous.copy()
    for t in range(k):
        m = assign == t
        if m.sum() == 0:
            continue           # keep the old centroid; an empty territory can refill
        out[t] = np.average(coords[m], axis=0, weights=w[m])
    return out


def solve(units: pd.DataFrame, n_reps: int, edges: set[tuple[str, str]] | None = None,
          seed: int = 42) -> tuple[np.ndarray, dict]:
    cfg = params()["territory"]
    rng = np.random.default_rng(seed)

    if edges is None:
        edges = knn_adjacency(units[["unit", "lat", "lon"]], k=cfg["adjacency_k"])

    total = units["workload"].sum()
    # 8% headroom: a hard capacity equal to mean load makes the last few units
    # unplaceable and forces overflow into whichever territory happens to be
    # nearest, which is worse than allowing modest slack up front.
    capacity = max(total / n_reps * 1.08, capacity_per_rep() * 0.5)

    centroids = _seed_centroids(units, n_reps, rng)
    assign = np.zeros(len(units), dtype=int)
    prev_obj = np.inf

    for it in range(cfg["max_iterations"]):
        assign = _assign_capacitated(units, centroids, capacity)
        assign = _repair_contiguity(units, assign, edges, centroids, capacity)
        assign = _rebalance(units, assign, edges, n_reps)
        assign = _repair_contiguity(units, assign, edges, centroids, capacity)
        centroids = _update_centroids(units, assign, n_reps, centroids)

        obj = _objective(units, assign, centroids)
        if abs(prev_obj - obj) / max(prev_obj, 1e-9) < 1e-4:
            log.info("  converged at iteration %d (objective %.0f)", it + 1, obj)
            break
        prev_obj = obj

    # Order matters: polish for compactness LAST, and only via moves that keep
    # both capacity and contiguity. Running the distance polish before the
    # balance pass would let it undo the balance gains.
    assign = _boundary_swaps(units, assign, centroids, edges, capacity)
    return assign, evaluate(units, assign, edges, centroids)


def _rebalance(units: pd.DataFrame, assign: np.ndarray, edges: set[tuple[str, str]],
               n_territories: int, max_passes: int = 40) -> np.ndarray:
    """Push workload toward the mean by moving boundary units downhill.

    WHY THIS IS A SEPARATE PASS
    ---------------------------
    Capacity is only an UPPER bound. Nothing in the greedy assignment pulls a
    territory UP toward the mean, so a centroid seeded in a sparse region keeps
    whatever little workload happens to be near it. The result is 100%
    contiguous, compact, and badly imbalanced -- CV around 0.28 against a 0.10
    target, which fails gate G4 even though the map looks tidy.

    The fix is a dedicated balance pass with a squared-deviation objective:
    moving a unit from a heavy territory to a light adjacent one is accepted
    when it reduces total squared deviation from the mean load AND leaves the
    source territory connected. Squared (not absolute) deviation matters -- it
    makes the pass attack the worst-balanced territories first, which is what
    drives the max/min ratio down rather than just shuffling the middle.
    """
    assign = assign.copy()
    unit_ids = units["unit"].to_numpy()
    idx_of = {u: i for i, u in enumerate(unit_ids)}
    workload = units["workload"].to_numpy(dtype=float)

    neighbours: dict[str, set[str]] = {u: set() for u in unit_ids}
    for a, b in edges:
        if a in neighbours and b in neighbours:
            neighbours[a].add(b)
            neighbours[b].add(a)

    target = workload.sum() / n_territories
    loads = np.array([workload[assign == t].sum() for t in range(n_territories)])

    def _cv(ld: np.ndarray) -> float:
        a = ld[ld > 0]
        return float(a.std() / a.mean()) if len(a) and a.mean() > 0 else 0.0

    moved_total = 0
    best_cv = _cv(loads)
    stalled = 0

    for _ in range(max_passes):
        moved = 0
        # Work from the heaviest territories down: they have the most to give.
        # The `loads[src] <= target` guard is load-bearing. Dropping it and
        # letting every territory donate whenever the squared-deviation test
        # improves was measured and made things WORSE (CV 0.165 -> 0.203 at 60
        # reps): below-target territories start trading units with each other,
        # each move locally improving while collectively churning the map and
        # blocking the heavy territories from shedding into them. Donors must be
        # over target.
        for src in np.argsort(-loads):
            if loads[src] <= target:
                continue
            members = [u for u in unit_ids if assign[idx_of[u]] == src]
            if len(members) <= 1:
                continue

            for u in sorted(members, key=lambda x: workload[idx_of[x]]):
                i = idx_of[u]
                w = workload[i]
                if w <= 0:
                    continue
                cand = {assign[idx_of[nb]] for nb in neighbours[u]} - {src}
                if not cand:
                    continue

                best, best_gain = None, 0.0
                for dst in cand:
                    before = (loads[src] - target) ** 2 + (loads[dst] - target) ** 2
                    after = (loads[src] - w - target) ** 2 + (loads[dst] + w - target) ** 2
                    gain = before - after
                    if gain > best_gain:
                        best, best_gain = dst, gain
                if best is None:
                    continue

                # Never trade balance for a disconnected territory.
                remaining = {m for m in members if m != u}
                if remaining and len(_components(remaining, edges)) > 1:
                    continue

                assign[i] = best
                loads[src] -= w
                loads[best] += w
                members.remove(u)
                moved += 1
                if loads[src] <= target:
                    break
        moved_total += moved
        if moved == 0:
            break

        # Stall detection. Once CV stops improving, further passes just trade
        # units back and forth across the same boundaries -- each move locally
        # reduces squared deviation, the next one undoes it, and the loop churns
        # ~110 units per pass at a flat CV. Without this it runs all 40 passes
        # every time, wasting roughly 30s per solve and burying the real
        # convergence signal in log noise.
        cv = _cv(loads)
        if cv < best_cv - 1e-4:
            best_cv, stalled = cv, 0
        else:
            stalled += 1
            if stalled >= 3:
                break

    if moved_total:
        log.info("  rebalance moved %d units, CV %.3f", moved_total, _cv(loads))
    return assign


def _objective(units: pd.DataFrame, assign: np.ndarray, centroids: np.ndarray) -> float:
    coords = units[["lat", "lon"]].to_numpy(dtype=float)
    w = units["workload"].to_numpy(dtype=float)
    d = haversine_miles(coords[:, 0], coords[:, 1],
                        centroids[assign][:, 0], centroids[assign][:, 1])
    return float((d * (w + 1.0)).sum())


def _boundary_swaps(units: pd.DataFrame, assign: np.ndarray, centroids: np.ndarray,
                    edges: set[tuple[str, str]], capacity: float,
                    max_passes: int = 3) -> np.ndarray:
    """Move boundary units to a neighbouring territory when it strictly helps.

    A move is accepted only if it reduces weighted distance AND does not breach
    capacity AND does not disconnect either the source or destination territory.
    Checking contiguity inside the accept test is what stops the polish step
    from quietly undoing the repair step.
    """
    assign = assign.copy()
    unit_ids = units["unit"].to_numpy()
    idx_of = {u: i for i, u in enumerate(unit_ids)}
    coords = units[["lat", "lon"]].to_numpy(dtype=float)
    workload = units["workload"].to_numpy(dtype=float)

    neighbours: dict[str, set[str]] = {u: set() for u in unit_ids}
    for a, b in edges:
        if a in neighbours and b in neighbours:
            neighbours[a].add(b)
            neighbours[b].add(a)

    moved_total = 0
    for _ in range(max_passes):
        moved = 0
        loads = np.array([workload[assign == t].sum() for t in range(len(centroids))])
        for u in unit_ids:
            i = idx_of[u]
            src = assign[i]
            cand = {assign[idx_of[nb]] for nb in neighbours[u]} - {src}
            if not cand:
                continue

            d_src = haversine_miles(coords[i, 0], coords[i, 1],
                                    centroids[src][0], centroids[src][1])
            for dst in cand:
                d_dst = haversine_miles(coords[i, 0], coords[i, 1],
                                        centroids[dst][0], centroids[dst][1])
                if d_dst >= d_src or loads[dst] + workload[i] > capacity:
                    continue
                # Would removing u disconnect the source territory?
                remaining = set(unit_ids[assign == src]) - {u}
                if remaining and len(_components(remaining, edges)) > 1:
                    continue
                assign[i] = dst
                loads[src] -= workload[i]
                loads[dst] += workload[i]
                moved += 1
                break
        moved_total += moved
        if moved == 0:
            break
    if moved_total:
        log.info("  boundary polish moved %d units", moved_total)
    return assign


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #

def evaluate(units: pd.DataFrame, assign: np.ndarray,
             edges: set[tuple[str, str]], centroids: np.ndarray | None = None) -> dict:
    """The four metrics reported before and after. Nothing else is claimed."""
    unit_ids = units["unit"].to_numpy()
    workload = units["workload"].to_numpy(dtype=float)
    coords = units[["lat", "lon"]].to_numpy(dtype=float)

    territories = sorted(set(assign.tolist()))
    loads = np.array([workload[assign == t].sum() for t in territories])
    active = loads[loads > 0]

    if centroids is None:
        centroids = np.array([
            coords[assign == t].mean(axis=0) if (assign == t).any() else [0.0, 0.0]
            for t in range(max(territories) + 1)
        ])

    d = haversine_miles(coords[:, 0], coords[:, 1],
                        centroids[assign][:, 0], centroids[assign][:, 1])
    weighted_dist = float((d * workload).sum() / max(workload.sum(), 1e-9))

    contiguous = 0
    for t in territories:
        members = set(unit_ids[assign == t])
        if not members or len(_components(members, edges)) == 1:
            contiguous += 1

    high_decile_covered = float(
        units.loc[np.isin(assign, territories), "high_decile_hcps"].sum())

    return {
        "n_territories": len(territories),
        "n_active_territories": int((loads > 0).sum()),
        "workload_total": float(workload.sum()),
        "workload_mean": float(active.mean()) if len(active) else 0.0,
        "workload_max": float(active.max()) if len(active) else 0.0,
        "workload_min": float(active.min()) if len(active) else 0.0,
        "imbalance_ratio": float(active.max() / active.min()) if len(active) and active.min() > 0 else None,
        "workload_cv": float(active.std() / active.mean()) if len(active) and active.mean() > 0 else None,
        "mean_weighted_distance_mi": round(weighted_dist, 2),
        "contiguity_rate": round(contiguous / len(territories), 4),
        "n_contiguous": contiguous,
        "high_decile_hcps_covered": high_decile_covered,
    }


def run(n_reps_list: list[int] | None = None) -> pd.DataFrame:
    cfg = params()["territory"]
    proc = path("processed")
    planned = read_parquet(proc / "hcp_call_plan.parquet")

    units = build_units(planned)
    edges = knn_adjacency(units[["unit", "lat", "lon"]], k=cfg["adjacency_k"])
    log.info("adjacency: %d edges over %d units (method=%s, k=%d)",
             len(edges), len(units), cfg["adjacency_method"], cfg["adjacency_k"])

    n_reps_list = n_reps_list or cfg["n_reps_presolve"]
    default_n = cfg["n_reps_default"]

    # --- baseline ("before") ------------------------------------------------
    base_assign = baseline_alignment(units, default_n)
    base_stats = evaluate(units, base_assign, edges)
    base_stats["alignment"] = "baseline"
    base_stats["n_reps"] = default_n
    log.info("BASELINE  @%d reps: imbalance %.2fx, CV %.3f, contiguity %.1f%%, "
             "mean travel %.0f mi",
             default_n, base_stats["imbalance_ratio"] or 0, base_stats["workload_cv"] or 0,
             100 * base_stats["contiguity_rate"], base_stats["mean_weighted_distance_mi"])

    all_stats = [base_stats]
    assignments = {f"baseline_{default_n}": base_assign}

    for n in n_reps_list:
        log.info("solving optimised alignment @ %d reps", n)
        assign, stats = solve(units, n, edges)
        stats["alignment"] = "optimised"
        stats["n_reps"] = n
        all_stats.append(stats)
        assignments[f"optimised_{n}"] = assign
        log.info("OPTIMISED @%d reps: imbalance %.2fx, CV %.3f, contiguity %.1f%%, "
                 "mean travel %.0f mi",
                 n, stats["imbalance_ratio"] or 0, stats["workload_cv"] or 0,
                 100 * stats["contiguity_rate"], stats["mean_weighted_distance_mi"])

    stats_df = pd.DataFrame(all_stats)
    write_parquet(stats_df, proc / "territory_stats.parquet")

    # Long-format unit assignments, one row per (alignment, n_reps, unit).
    rows = []
    for key, assign in assignments.items():
        alignment, n = key.rsplit("_", 1)
        tmp = units.copy()
        tmp["alignment"] = alignment
        tmp["n_reps"] = int(n)
        tmp["territory"] = assign
        rows.append(tmp)
    unit_assign = pd.concat(rows, ignore_index=True)
    write_parquet(unit_assign, proc / "territory_assignments.parquet")

    # Per-territory rollup for the workload bar chart on /territories.
    terr = (unit_assign.groupby(["alignment", "n_reps", "territory"])
            .agg(workload=("workload", "sum"), n_units=("unit", "count"),
                 n_hcps=("n_hcps", "sum"), n_targets=("n_targets", "sum"),
                 high_decile_hcps=("high_decile_hcps", "sum"),
                 opportunity=("opportunity", "sum"),
                 lat=("lat", "mean"), lon=("lon", "mean"))
            .reset_index())
    write_parquet(terr, proc / "territory_summary.parquet")

    # Headline comparison at the default force size.
    opt = stats_df[(stats_df["alignment"] == "optimised") & (stats_df["n_reps"] == default_n)]
    if len(opt):
        o = opt.iloc[0]
        record("territory_headline",
               n_reps=default_n,
               imbalance_before=round(base_stats["imbalance_ratio"] or 0, 2),
               imbalance_after=round(float(o["imbalance_ratio"] or 0), 2),
               cv_before=round(base_stats["workload_cv"] or 0, 4),
               cv_after=round(float(o["workload_cv"] or 0), 4),
               contiguity_before=base_stats["contiguity_rate"],
               contiguity_after=float(o["contiguity_rate"]),
               travel_before=base_stats["mean_weighted_distance_mi"],
               travel_after=float(o["mean_weighted_distance_mi"]),
               travel_reduction_pct=round(
                   1 - float(o["mean_weighted_distance_mi"])
                   / max(base_stats["mean_weighted_distance_mi"], 1e-9), 4))
    return stats_df


if __name__ == "__main__":
    run()
