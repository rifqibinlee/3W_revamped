import json

from app.siteplanning.cctv import (
    _azimuth_degrees,
    _create_hex_grid_qgis,
    _wedge_buffer,
    run_cctv_pipeline,
)


def test_azimuth_due_north_is_zero() -> None:
    assert _azimuth_degrees(0, 0, 0, 1) == 0


def test_azimuth_due_east_is_90() -> None:
    assert abs(_azimuth_degrees(0, 0, 1, 0) - 90) < 1e-9


def test_azimuth_due_south_is_180() -> None:
    assert abs(_azimuth_degrees(0, 0, 0, -1) - 180) < 1e-9


def test_wedge_buffer_apex_is_at_camera_point() -> None:
    wedge = _wedge_buffer(101.5, 3.1, azimuth_deg=0, hfov_deg=90, range_m=50)
    assert wedge.is_valid
    # First and last ring coordinates are both the apex (closing the polygon)
    coords = list(wedge.exterior.coords)
    assert coords[0] == (101.5, 3.1)
    assert coords[-1] == (101.5, 3.1)


def test_wedge_buffer_points_extend_within_expected_range() -> None:
    range_m = 100.0
    wedge = _wedge_buffer(0, 0, azimuth_deg=0, hfov_deg=90, range_m=range_m)
    range_deg = range_m / 111320.0
    # Every non-apex vertex should sit within range_deg of the origin
    for x, y in wedge.exterior.coords:
        dist = (x**2 + y**2) ** 0.5
        assert dist <= range_deg + 1e-9


def test_hex_grid_covers_bounds() -> None:
    polys = _create_hex_grid_qgis((0, 0, 1, 1), hspacing=0.2, vspacing=0.2)
    assert len(polys) > 0
    # Every polygon should be a valid closed hexagon-ish shape
    for poly in polys:
        assert poly.is_valid


def test_full_pipeline_with_synthetic_inputs(tmp_path) -> None:
    building_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [0, 0.001], [0.001, 0.001], [0.001, 0], [0, 0]]],
            },
        }],
    }
    parking_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0.002, 0], [0.002, 0.001], [0.003, 0.001], [0.003, 0], [0.002, 0]]],
            },
        }],
    }
    poles_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Point", "coordinates": [0.0025, 0.0005]},
        }],
    }

    building_path = tmp_path / "building.geojson"
    parking_path = tmp_path / "parking.geojson"
    poles_path = tmp_path / "poles.geojson"
    building_path.write_text(json.dumps(building_geojson))
    parking_path.write_text(json.dumps(parking_geojson))
    poles_path.write_text(json.dumps(poles_geojson))

    camera_csv = tmp_path / "cameras.csv"
    camera_csv.write_text("camera_type,hfov_deg,range_m,unit_price_rm\nType A,90,30,500\n")
    offset_csv = tmp_path / "offsets.csv"
    offset_csv.write_text("offset\n0\n120\n240\n")

    results = run_cctv_pipeline(str(building_path), str(parking_path), str(poles_path), str(camera_csv), str(offset_csv))

    assert set(results.keys()) == {
        "dissolved_buildings", "candidate_cctv", "surv_area", "aoi", "hex_grid",
        "poles", "cand_cctv_clean", "wedge", "camera_cost_summary",
    }
    for layer in results.values():
        assert layer["type"] == "FeatureCollection"

    # Building has 4 distinct corners -> 4 candidate points, each x3 offsets
    assert len(results["cand_cctv_clean"]["features"]) > 0
    assert len(results["wedge"]["features"]) == len(results["cand_cctv_clean"]["features"])


def test_full_pipeline_prices_correctly_when_camera_type_is_not_named_type_a(tmp_path) -> None:
    """Regression test: every candidate position used to be hardcoded
    to camera_type "Type A" before merging with the caller's camera
    spec table, so if the caller's CSV named its camera type anything
    else, the merge silently dropped unit_price_rm to null/0 for every
    position with no error."""
    building_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 0.001], [0.001, 0.001], [0.001, 0], [0, 0]]]},
        }],
    }
    parking_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[[0.002, 0], [0.002, 0.001], [0.003, 0.001], [0.003, 0], [0.002, 0]]]},
        }],
    }
    poles_geojson = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [0.0025, 0.0005]}}],
    }

    building_path = tmp_path / "building.geojson"
    parking_path = tmp_path / "parking.geojson"
    poles_path = tmp_path / "poles.geojson"
    building_path.write_text(json.dumps(building_geojson))
    parking_path.write_text(json.dumps(parking_geojson))
    poles_path.write_text(json.dumps(poles_geojson))

    camera_csv = tmp_path / "cameras.csv"
    camera_csv.write_text("camera_type,hfov_deg,range_m,unit_price_rm\nPTZ,90,50,3500\n")
    offset_csv = tmp_path / "offsets.csv"
    offset_csv.write_text("offset\n0\n120\n240\n")

    results = run_cctv_pipeline(str(building_path), str(parking_path), str(poles_path), str(camera_csv), str(offset_csv))

    cost_rows = results["camera_cost_summary"]["features"]
    assert len(cost_rows) == 1
    assert cost_rows[0]["properties"]["camera_type"] == "PTZ"
    assert cost_rows[0]["properties"]["unit_price_rm"] == 3500
    assert cost_rows[0]["properties"]["total_cost_rm"] > 0
