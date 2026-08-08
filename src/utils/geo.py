"""Geography helpers: distance, ZIP handling, adjacency graphs.

No geopandas dependency. Great-circle distance is computed directly and the
contiguity graph is built from centroids. Both choices are documented
limitations, not oversights -- see README section 6.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EARTH_RADIUS_MI = 3958.7613


def haversine_miles(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Great-circle distance in miles. Broadcasts over numpy arrays."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, dtype=float)) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_MI * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def pairwise_miles(lat_a, lon_a, lat_b, lon_b) -> np.ndarray:
    """Full distance matrix between point set A (n) and point set B (m) -> (n, m)."""
    lat_a = np.asarray(lat_a, dtype=float)[:, None]
    lon_a = np.asarray(lon_a, dtype=float)[:, None]
    lat_b = np.asarray(lat_b, dtype=float)[None, :]
    lon_b = np.asarray(lon_b, dtype=float)[None, :]
    return haversine_miles(lat_a, lon_a, lat_b, lon_b)


def zip5(value) -> str | None:
    """Normalise a CMS ZIP to five digits.

    CMS ships ZIP+4 in some files and drops leading zeros wherever a column was
    ever read as numeric. Both are handled here so neither is handled twice.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    s = str(value).strip().split("-")[0]
    s = "".join(ch for ch in s if ch.isdigit())
    if not s:
        return None
    return s[:5].zfill(5)


def zip3(value) -> str | None:
    z = zip5(value)
    return z[:3] if z else None


def knn_adjacency(units: pd.DataFrame, k: int = 6) -> set[tuple[str, str]]:
    """Symmetric k-nearest-neighbour adjacency over unit centroids.

    A documented approximation of true queen contiguity. Real ZCTA polygons
    give exact adjacency; centroid k-NN over-connects across water and
    under-connects in sparse western geographies. Which method was used is
    recorded in the manifest and stated on the /method route.

    ``units`` needs columns: unit, lat, lon.
    """
    ids = units["unit"].to_numpy()
    dist = pairwise_miles(units["lat"], units["lon"], units["lat"], units["lon"])
    np.fill_diagonal(dist, np.inf)
    k = min(k, len(ids) - 1)
    nearest = np.argsort(dist, axis=1)[:, :k]

    edges: set[tuple[str, str]] = set()
    for i, row in enumerate(nearest):
        for j in row:
            a, b = ids[i], ids[j]
            edges.add((a, b) if a < b else (b, a))
    return edges


def census_region(state: str) -> str:
    """US Census region. Used as a peer-group dimension in the potential model."""
    return _STATE_REGION.get(state, "Unknown")


_NORTHEAST = ["CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"]
_MIDWEST = ["IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"]
_SOUTH = ["DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV", "AL", "KY", "MS", "TN", "AR", "LA", "OK", "TX"]
_WEST = ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"]

_STATE_REGION: dict[str, str] = {
    **dict.fromkeys(_NORTHEAST, "Northeast"),
    **dict.fromkeys(_MIDWEST, "Midwest"),
    **dict.fromkeys(_SOUTH, "South"),
    **dict.fromkeys(_WEST, "West"),
}

# Approximate population-weighted state centroids (lat, lon). Used to place
# synthetic ZIP3 units and as a fallback when Gazetteer data is unavailable.
STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "AL": (32.8, -86.8), "AK": (61.4, -149.0), "AZ": (33.7, -112.0), "AR": (34.9, -92.4),
    "CA": (36.8, -119.7), "CO": (39.6, -105.0), "CT": (41.6, -72.7), "DE": (39.3, -75.5),
    "DC": (38.9, -77.0), "FL": (28.6, -81.6), "GA": (33.6, -84.2), "HI": (21.4, -157.9),
    "ID": (43.6, -116.2), "IL": (41.6, -88.2), "IN": (39.9, -86.2), "IA": (41.7, -93.5),
    "KS": (38.5, -97.3), "KY": (38.0, -85.0), "LA": (30.5, -91.1), "ME": (44.0, -69.9),
    "MD": (39.1, -76.7), "MA": (42.3, -71.4), "MI": (42.9, -84.2), "MN": (45.0, -93.3),
    "MS": (32.5, -89.9), "MO": (38.7, -92.4), "MT": (46.6, -111.5), "NE": (41.1, -96.2),
    "NV": (36.3, -115.2), "NH": (43.1, -71.5), "NJ": (40.4, -74.4), "NM": (35.1, -106.5),
    "NY": (41.3, -74.2), "NC": (35.6, -79.4), "ND": (47.0, -100.5), "OH": (40.2, -82.8),
    "OK": (35.5, -97.5), "OR": (44.6, -122.9), "PA": (40.5, -77.0), "RI": (41.7, -71.5),
    "SC": (33.9, -80.9), "SD": (44.2, -100.2), "TN": (35.9, -86.5), "TX": (30.8, -97.3),
    "UT": (40.5, -111.9), "VT": (44.1, -72.7), "VA": (37.8, -77.7), "WA": (47.4, -121.9),
    "WV": (38.7, -80.7), "WI": (43.5, -89.3), "WY": (42.9, -106.5),
}
