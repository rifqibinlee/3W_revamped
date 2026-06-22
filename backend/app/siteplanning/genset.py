"""Generator/substation routing: road-network distance from a cell site
to nearby substations.

Ports `genset_pipeline.py`. Overpass (finding candidate substations) stays
a frontend concern in the legacy design — this takes a pre-fetched
substation list and just computes road routes/distances via OSMnx.

The only structural change from the legacy version: `_get_road_graph` is
now an injectable parameter on `route_substations` (defaulting to the
real OSMnx download) so tests can supply a tiny synthetic graph instead
of hitting the live OpenStreetMap API.
"""

import logging
import time
from collections.abc import Callable

import networkx as nx
import osmnx as ox

logger = logging.getLogger(__name__)

ox.settings.log_console = False
ox.settings.use_cache = True

MAX_ROAD_DIST_M = 2000
GRAPH_BUFFER_M = 2500


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
