"""Generator/substation routing: road-network distance from a cell site
to nearby substations and electric poles.

Two entry points:
  route_substations()      — per-site, takes pre-fetched substations (legacy API)
  find_all_power_sources() — per-site, fetches substations via OSMnx AND routes
                             to electric poles from local GeoPackage — both via
                             road network, sharing a single graph download
"""

import logging
import math
import time
from collections.abc import Callable

import networkx as nx
import osmnx as ox

logger = logging.getLogger(__name__)

ox.settings.log_console = False
ox.settings.use_cache = True

MAX_ROAD_DIST_M  = 2000
GRAPH_BUFFER_M   = 2500
OVERPASS_RADIUS  = 3500   # wider initial search; road routing trims to 2 km


def _get_road_graph(lat: float, lng: float, radius_m: int = GRAPH_BUFFER_M):
    """Downloads (or loads from OSMnx cache) the undirected road network
    within radius_m metres of the given point. Real network call — tests
    inject a fake graph_provider instead of exercising this directly."""
    g = ox.graph_from_point((lat, lng), dist=radius_m, network_type="all", simplify=True)
    return ox.convert.to_undirected(g)


def _nearest_node(g, lat: float, lng: float):
    return ox.distance.nearest_nodes(g, X=lng, Y=lat)


def _route_to_coords(g, route_nodes: list) -> list:
    """Converts a node-ID path to [[lat, lng], ...] for Leaflet/MapLibre polylines."""
    return [[g.nodes[n]["y"], g.nodes[n]["x"]] for n in route_nodes]


def route_substations(
    site_lat: float,
    site_lng: float,
    substations: list,
    max_road_dist_m: int = MAX_ROAD_DIST_M,
    graph_buffer_m: int = GRAPH_BUFFER_M,
    graph_provider: Callable[[float, float, int], object] | None = None,
) -> dict:
    """For each substation, computes the shortest road distance from the
    site and returns those within max_road_dist_m metres, sorted nearest
    first.

    graph_provider lets tests substitute a synthetic networkx graph in
    place of the real OSMnx download (_get_road_graph).
    """
    t0 = time.time()
    get_graph = graph_provider or _get_road_graph

    if not substations:
        return {
            "site": {"lat": site_lat, "lng": site_lng},
            "results": [],
            "substations_checked": 0,
            "substations_within_2km": 0,
            "error": "No substations provided",
            "elapsed_s": 0,
        }

    try:
        g = get_graph(site_lat, site_lng, graph_buffer_m)
    except Exception as e:
        return {
            "site": {"lat": site_lat, "lng": site_lng},
            "results": [],
            "substations_checked": len(substations),
            "substations_within_2km": 0,
            "error": f"Road network download failed: {e}",
            "elapsed_s": round(time.time() - t0, 2),
        }

    try:
        site_node = _nearest_node(g, site_lat, site_lng)
    except Exception as e:
        return {
            "site": {"lat": site_lat, "lng": site_lng},
            "results": [],
            "substations_checked": len(substations),
            "substations_within_2km": 0,
            "error": f"Could not snap site to road network: {e}",
            "elapsed_s": round(time.time() - t0, 2),
        }

    results = []
    for sub in substations:
        try:
            sub_node = _nearest_node(g, sub["lat"], sub["lng"])
            road_dist_m = nx.shortest_path_length(g, site_node, sub_node, weight="length")

            if road_dist_m > max_road_dist_m:
                continue

            route_nodes = nx.shortest_path(g, site_node, sub_node, weight="length")
            results.append({
                "name": sub.get("name", "Substation"),
                "lat": sub["lat"],
                "lng": sub["lng"],
                "osm_id": sub.get("osm_id", ""),
                "road_dist_m": round(road_dist_m, 1),
                "road_dist_km": round(road_dist_m / 1000, 3),
                "route_coords": _route_to_coords(g, route_nodes),
            })

        except nx.NetworkXNoPath:
            logger.debug("No path to %s", sub.get("name"))
        except nx.NodeNotFound:
            logger.debug("Node not found for %s", sub.get("name"))
        except Exception as e:
            logger.warning("Routing error for %s: %s", sub.get("name"), e)

    results.sort(key=lambda x: x["road_dist_m"])
    elapsed = round(time.time() - t0, 2)

    return {
        "site": {"lat": site_lat, "lng": site_lng},
        "results": results,
        "substations_checked": len(substations),
        "substations_within_2km": len(results),
        "error": None,
        "elapsed_s": elapsed,
    }


def _route_points(
    g,
    site_node,
    points: list[dict],
    max_road_dist_m: int,
) -> list[dict]:
    """Road-route the site to each point in `points` using a pre-loaded graph.

    Each point must have keys: lat, lng, plus any extra keys that are passed
    through verbatim.  Returns only points reachable within max_road_dist_m,
    sorted nearest first, each augmented with road_dist_m / road_dist_km /
    route_coords.
    """
    results = []
    for pt in points:
        try:
            pt_node = _nearest_node(g, pt["lat"], pt["lng"])
            road_dist_m = nx.shortest_path_length(g, site_node, pt_node, weight="length")
            if road_dist_m > max_road_dist_m:
                continue
            route_nodes = nx.shortest_path(g, site_node, pt_node, weight="length")
            results.append({
                **pt,
                "road_dist_m":  round(road_dist_m, 1),
                "road_dist_km": round(road_dist_m / 1000, 3),
                "route_coords": _route_to_coords(g, route_nodes),
            })
        except nx.NetworkXNoPath:
            pass
        except nx.NodeNotFound:
            pass
        except Exception as exc:
            logger.debug("Routing error for point %s: %s", pt, exc)
    results.sort(key=lambda x: x["road_dist_m"])
    return results


# ── Substation fetch via osmnx ───────────────────────────────────────────────

def fetch_substations_overpass(lat: float, lng: float,
                                radius_m: int = OVERPASS_RADIUS,
                                timeout: int = 25) -> list[dict]:
    """Fetch power substations near (lat, lng) using osmnx.features_from_point.
    Returns list of {osm_id, name, operator, voltage, lat, lng}."""
    try:
        gdf = ox.features_from_point(
            (lat, lng),
            tags={"power": "substation"},
            dist=radius_m,
        )
    except Exception as exc:
        logger.warning("osmnx substation query failed: %s", exc)
        return []

    results = []
    for idx, row in gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        # centroid works for both point and polygon geometries
        c = geom.centroid
        slat, slng = c.y, c.x
        # osm_id from MultiIndex (element_type, osmid)
        osm_id = str(idx[1]) if isinstance(idx, tuple) else str(idx)
        name = row.get("name") or row.get("operator") or "Substation"
        results.append({
            "osm_id":   osm_id,
            "name":     str(name) if name and str(name) != "nan" else "Substation",
            "operator": str(row.get("operator", "") or ""),
            "voltage":  str(row.get("voltage", "") or ""),
            "lat":      slat,
            "lng":      slng,
        })
    return results


# ── Combined finder ──────────────────────────────────────────────────────────

def find_all_power_sources(
    site_lat: float,
    site_lng: float,
    max_road_dist_m: int = MAX_ROAD_DIST_M,
    graph_buffer_m: int = GRAPH_BUFFER_M,
) -> dict:
    """
    Find ALL substations and electric poles within max_road_dist_m road distance.
    Downloads the OSMnx road graph once and reuses it for routing to both
    substations and poles.

    Returns:
        {
          "substations": [...],   # road-routed, all within threshold
          "electric_poles": [...],# road-routed, all within threshold
          "substations_found": int,
          "poles_found": int,
          "error": str | None,
          "elapsed_s": float,
        }
    """
    from app.siteplanning.electric_poles import find_poles_within

    t0 = time.time()
    error: str | None = None

    # ── Download road graph once ─────────────────────────────────────────────
    try:
        g = _get_road_graph(site_lat, site_lng, graph_buffer_m)
        site_node = _nearest_node(g, site_lat, site_lng)
    except Exception as exc:
        logger.warning("Road graph download failed for (%.5f, %.5f): %s", site_lat, site_lng, exc)
        return {
            "substations":       [],
            "electric_poles":    [],
            "substations_found": 0,
            "poles_found":       0,
            "error":             f"Road network download failed: {exc}",
            "elapsed_s":         round(time.time() - t0, 2),
        }

    # ── Substations ──────────────────────────────────────────────────────────
    sub_candidates = fetch_substations_overpass(site_lat, site_lng, radius_m=OVERPASS_RADIUS)
    routed_subs = _route_points(g, site_node, sub_candidates, max_road_dist_m)

    sub_results: list[dict] = []
    for r in routed_subs:
        sub_results.append({
            "power_source_type": "Substation",
            "name":              r.get("name", "Substation"),
            "osm_id":            r.get("osm_id", ""),
            "operator":          r.get("operator", ""),
            "voltage":           r.get("voltage", ""),
            "lat":               r["lat"],
            "lon":               r["lng"],
            "dist_m":            r["road_dist_m"],
            "dist_km":           r["road_dist_km"],
            "dist_type":         "road",
            "route_coords":      r["route_coords"],
        })

    # ── Electric poles ───────────────────────────────────────────────────────
    # Use a wider straight-line pre-filter (graph_buffer_m) to find candidates,
    # then road-route to trim to max_road_dist_m.
    pole_candidates_raw = find_poles_within(site_lat, site_lng, radius_m=graph_buffer_m)
    pole_candidates = [
        {"lat": p["lat"], "lng": p["lon"], "osm_id": p["osm_id"], "powertype": p["powertype"]}
        for p in pole_candidates_raw
    ]
    routed_poles = _route_points(g, site_node, pole_candidates, max_road_dist_m)

    pole_results: list[dict] = []
    for r in routed_poles:
        pole_results.append({
            "power_source_type": "Electric Pole",
            "name":              f"Electric Pole ({r['powertype']})",
            "osm_id":            r["osm_id"],
            "operator":          "",
            "voltage":           "",
            "lat":               r["lat"],
            "lon":               r["lng"],
            "dist_m":            r["road_dist_m"],
            "dist_km":           r["road_dist_km"],
            "dist_type":         "road",
            "route_coords":      r["route_coords"],
            "powertype":         r["powertype"],
        })

    return {
        "substations":       sub_results,
        "electric_poles":    pole_results,
        "substations_found": len(sub_results),
        "poles_found":       len(pole_results),
        "error":             error,
        "elapsed_s":         round(time.time() - t0, 2),
    }
