"""Electric pole lookup from local GeoPackage.

Finds all electric power features (towers, poles, transformers) within a
straight-line radius of a site.  Road routing to every pole is impractical
at scale — poles sit on road corridors so straight-line distance is a
reasonable proxy for cable-run distance.
"""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import numpy as np
from scipy.spatial import cKDTree

log = logging.getLogger(__name__)

# Adjust if file moves
GPKG_PATH = Path(__file__).resolve().parents[3] / "wholemalaysia_electric_pole.gpkg"

POWER_TYPES = {"tower", "pole", "transformer", "substation", "insulator", "portal"}
_EARTH_R = 6_371_000.0


@lru_cache(maxsize=1)
def _load_index() -> tuple[cKDTree, "np.ndarray", "np.ndarray", list[str], list[str]]:
    """Load and index the electric poles GeoPackage (cached after first call)."""
    log.info("Loading electric poles from %s …", GPKG_PATH)
    gdf = gpd.read_file(GPKG_PATH)

    filtered = gdf[gdf["powertype"].isin(POWER_TYPES)].dropna(subset=["geometry"]).copy()
    if filtered.empty:
        log.warning("No powertype-filtered poles found — falling back to full dataset")
        filtered = gdf.dropna(subset=["geometry"]).copy()

    lats = filtered.geometry.y.values
    lons = filtered.geometry.x.values
    osm_ids   = filtered["osm_id"].astype(str).tolist()
    ptypes    = filtered["powertype"].fillna("").tolist()

    # KDTree on unit-sphere (x,y,z) — avoids haversine in the query loop
    lats_r = np.radians(lats)
    lons_r = np.radians(lons)
    xyz = np.column_stack([
        np.cos(lats_r) * np.cos(lons_r),
        np.cos(lats_r) * np.sin(lons_r),
        np.sin(lats_r),
    ])
    tree = cKDTree(xyz)

    log.info("  Indexed %d power features", len(filtered))
    return tree, lats, lons, osm_ids, ptypes


def _site_xyz(lat: float, lon: float) -> np.ndarray:
    lr, lo = math.radians(lat), math.radians(lon)
    return np.array([math.cos(lr) * math.cos(lo),
                     math.cos(lr) * math.sin(lo),
                     math.sin(lr)])


def find_poles_within(lat: float, lon: float,
                      radius_m: float = 2000) -> list[dict]:
    """
    Return all electric power features within radius_m metres (straight-line).

    Each result dict:
        osm_id, powertype, lat, lon,
        straight_dist_m, straight_dist_km
    Sorted by distance ascending.
    """
    tree, lats, lons, osm_ids, ptypes = _load_index()

    # Chord length for the given arc radius on a unit sphere
    chord = 2 * math.sin(radius_m / (2 * _EARTH_R))
    xyz   = _site_xyz(lat, lon)
    idxs  = tree.query_ball_point(xyz, chord)

    results = []
    for i in idxs:
        dlat = math.radians(lats[i] - lat)
        dlon = math.radians(lons[i] - lon)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat)) * math.cos(math.radians(lats[i]))
             * math.sin(dlon / 2) ** 2)
        dist_m = 2 * _EARTH_R * math.asin(math.sqrt(max(0.0, a)))
        results.append({
            "osm_id":           osm_ids[i],
            "powertype":        ptypes[i],
            "lat":              float(lats[i]),
            "lon":              float(lons[i]),
            "straight_dist_m":  round(dist_m, 1),
            "straight_dist_km": round(dist_m / 1000, 3),
        })

    results.sort(key=lambda x: x["straight_dist_m"])
    return results
