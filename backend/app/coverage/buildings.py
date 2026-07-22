"""
Fetch building footprints from OpenStreetMap via the Overpass API.

Returns building polygons in local XY metres (origin = SW corner of bounds),
ready for LOS intersection tests and Sionna scene construction.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_DEFAULT_FLOOR_H = 3.0   # metres per floor when num_floors is unknown
_DEFAULT_HEIGHT  = 9.0   # fallback building height (3 floors)


@dataclass
class Building:
    """A building polygon in local XY metres."""
    # Closed ring of (x, y) tuples in the local coordinate system
    ring_xy: list[tuple[float, float]]
    height_m: float = _DEFAULT_HEIGHT
    # Also keep original lng/lat ring for GeoJSON export
    ring_ll: list[tuple[float, float]] = field(default_factory=list)


def _parse_height(tags: dict[str, Any]) -> float:
    """Best-effort height from OSM tags (height, building:levels, etc.)."""
    raw = tags.get("height") or tags.get("building:height")
    if raw:
        try:
            return float(str(raw).replace("m", "").strip())
        except ValueError:
            pass
    levels = tags.get("building:levels") or tags.get("levels")
    if levels:
        try:
            return float(levels) * _DEFAULT_FLOOR_H
        except ValueError:
            pass
    return _DEFAULT_HEIGHT


def _ll_to_xy(
    lat: float, lng: float,
    origin_lat: float, origin_lng: float,
    m_lat: float, m_lng: float,
) -> tuple[float, float]:
    return (lng - origin_lng) * m_lng, (lat - origin_lat) * m_lat


def fetch(
    south: float, west: float, north: float, east: float,
    timeout: float = 25.0,
) -> list[Building]:
    """
    Query Overpass for all building ways in the bounding box and return
    Building objects in local XY metres (origin = SW corner).
    """
    # Overpass compact query: fetch building ways + their nodes in one request
    query = (
        f"[out:json][timeout:{int(timeout)}];"
        f"("
        f"  way[building]({south},{west},{north},{east});"
        f");"
        f"out body;"
        f">;"
        f"out skel qt;"
    )
    try:
        resp = httpx.post(
            _OVERPASS_URL,
            data={"data": query},
            timeout=timeout,
            headers={"User-Agent": "3W-coverage-sim/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Overpass request failed: %s", exc)
        return []

    # Index nodes by id
    nodes: dict[int, tuple[float, float]] = {}
    ways_raw: list[dict[str, Any]] = []
    for elem in data.get("elements", []):
        if elem["type"] == "node":
            nodes[elem["id"]] = (elem["lat"], elem["lon"])
        elif elem["type"] == "way":
            ways_raw.append(elem)

    # Coordinate-system helpers
    center_lat = (south + north) / 2
    m_lat = 6_371_000.0 * math.pi / 180.0
    m_lng = 6_371_000.0 * math.cos(math.radians(center_lat)) * math.pi / 180.0
    origin_lat, origin_lng = south, west

    buildings: list[Building] = []
    for way in ways_raw:
        node_ids: list[int] = way.get("nodes", [])
        if len(node_ids) < 4:   # need at least 3 distinct + closing node
            continue
        tags = way.get("tags", {})

        ring_ll: list[tuple[float, float]] = []
        ring_xy: list[tuple[float, float]] = []
        for nid in node_ids:
            if nid not in nodes:
                break
            lat, lng = nodes[nid]
            ring_ll.append((lng, lat))
            ring_xy.append(_ll_to_xy(lat, lng, origin_lat, origin_lng, m_lat, m_lng))
        else:
            if len(ring_xy) >= 4:
                buildings.append(Building(
                    ring_xy=ring_xy,
                    height_m=_parse_height(tags),
                    ring_ll=ring_ll,
                ))

    log.info("Overpass returned %d buildings for bbox %s,%s,%s,%s",
             len(buildings), south, west, north, east)
    return buildings
