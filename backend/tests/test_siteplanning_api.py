def test_cctv_run_endpoint(client) -> None:
    payload = {
        "building": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 0.001], [0.001, 0.001], [0.001, 0], [0, 0]]]},
            }],
        },
        "parking": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [[[0.002, 0], [0.002, 0.001], [0.003, 0.001], [0.003, 0], [0.002, 0]]]},
            }],
        },
        "poles": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature", "properties": {},
                "geometry": {"type": "Point", "coordinates": [0.0025, 0.0005]},
            }],
        },
        "cameras": [{"camera_type": "Type A", "hfov_deg": 90, "range_m": 30, "unit_price_rm": 500}],
        "offsets": [0, 120, 240],
    }
    resp = client.post("/siteplanning/cctv/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert "wedge" in body
    assert body["wedge"]["type"] == "FeatureCollection"


def test_genset_route_endpoint_handles_no_substations(client) -> None:
    resp = client.post(
        "/siteplanning/genset/route",
        json={"site_lat": 3.1, "site_lng": 101.5, "substations": []},
    )
    assert resp.status_code == 200
    assert resp.json()["error"] == "No substations provided"
