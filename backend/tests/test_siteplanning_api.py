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


def test_genset_bulk_site_ids_parses_csv_with_site_id_header(client) -> None:
    csv_content = b"Site_ID,notes\nN00377,foo\nN00412,bar\n"
    resp = client.post(
        "/siteplanning/genset/bulk-site-ids",
        files={"file": ("sites.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json() == ["N00377", "N00412"]


def test_genset_bulk_site_ids_falls_back_to_first_column(client) -> None:
    csv_content = b"id,notes\nN00377,foo\n"
    resp = client.post(
        "/siteplanning/genset/bulk-site-ids",
        files={"file": ("sites.csv", csv_content, "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json() == ["N00377"]


def test_genset_bulk_site_ids_rejects_unreadable_file(client) -> None:
    resp = client.post(
        "/siteplanning/genset/bulk-site-ids",
        files={"file": ("sites.xlsx", b"not a real xlsx", "application/octet-stream")},
    )
    assert resp.status_code == 400
