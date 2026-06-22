import networkx as nx

from app.siteplanning.genset import route_substations

# A tiny 4-node line graph: site(0) -- 100m -- A(1) -- 100m -- B(2) -- 5000m -- C(3)
# A is within 2km, B is within 2km (200m total), C is not (5200m total).


def _make_graph():
    g = nx.Graph()
    g.add_node(0, x=101.000, y=3.000)
    g.add_node(1, x=101.001, y=3.000)
    g.add_node(2, x=101.002, y=3.000)
    g.add_node(3, x=101.100, y=3.000)
    g.add_edge(0, 1, length=100)
    g.add_edge(1, 2, length=100)
    g.add_edge(2, 3, length=5000)
    return g


def _fake_graph_provider(lat, lng, radius_m):
    return _make_graph()


def _fake_nearest_node_patch(monkeypatch):
    """route_substations calls _nearest_node(g, lat, lng) via OSMnx — patch
    it to just return the node whose (y, x) matches, avoiding any need for
    a real spatial index."""
    def _nearest(g, lat, lng):
        for n, data in g.nodes(data=True):
            if abs(data["y"] - lat) < 1e-6 and abs(data["x"] - lng) < 1e-6:
                return n
        raise ValueError("no matching node")

    import app.siteplanning.genset as genset_module
    monkeypatch.setattr(genset_module, "_nearest_node", _nearest)


def test_filters_substations_beyond_max_distance(monkeypatch) -> None:
    _fake_nearest_node_patch(monkeypatch)
    substations = [
        {"osm_id": "a", "name": "Sub A", "lat": 3.000, "lng": 101.001},
        {"osm_id": "b", "name": "Sub B", "lat": 3.000, "lng": 101.002},
        {"osm_id": "c", "name": "Sub C", "lat": 3.000, "lng": 101.100},
    ]
    result = route_substations(3.000, 101.000, substations, graph_provider=_fake_graph_provider)

    assert result["substations_checked"] == 3
    assert result["substations_within_2km"] == 2
    names = {r["name"] for r in result["results"]}
    assert names == {"Sub A", "Sub B"}


def test_results_sorted_nearest_first(monkeypatch) -> None:
    _fake_nearest_node_patch(monkeypatch)
    substations = [
        {"osm_id": "b", "name": "Sub B", "lat": 3.000, "lng": 101.002},
        {"osm_id": "a", "name": "Sub A", "lat": 3.000, "lng": 101.001},
    ]
    result = route_substations(3.000, 101.000, substations, graph_provider=_fake_graph_provider)

    assert [r["name"] for r in result["results"]] == ["Sub A", "Sub B"]
    assert result["results"][0]["road_dist_m"] == 100.0
    assert result["results"][1]["road_dist_m"] == 200.0


def test_route_coords_follow_the_path(monkeypatch) -> None:
    _fake_nearest_node_patch(monkeypatch)
    substations = [{"osm_id": "b", "name": "Sub B", "lat": 3.000, "lng": 101.002}]
    result = route_substations(3.000, 101.000, substations, graph_provider=_fake_graph_provider)

    route = result["results"][0]["route_coords"]
    assert route == [[3.000, 101.000], [3.000, 101.001], [3.000, 101.002]]


def test_empty_substations_list_returns_error() -> None:
    result = route_substations(3.000, 101.000, [], graph_provider=_fake_graph_provider)
    assert result["error"] == "No substations provided"
    assert result["results"] == []


def test_graph_download_failure_is_handled_gracefully() -> None:
    def _broken_provider(lat, lng, radius_m):
        raise RuntimeError("network unreachable")

    result = route_substations(
        3.000, 101.000, [{"osm_id": "a", "name": "A", "lat": 3.0, "lng": 101.001}],
        graph_provider=_broken_provider,
    )
    assert "Road network download failed" in result["error"]
    assert result["results"] == []
