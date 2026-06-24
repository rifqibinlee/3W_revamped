import pytest


@pytest.fixture(autouse=True)
def _isolate_parquet_dir(tmp_path, monkeypatch):
    """These tests assert on an empty-data baseline, so they must not see
    whatever real parquet files happen to exist at the default location
    (e.g. after a real ETL run) — same isolation every other analytics
    test file already does via monkeypatch + tmp_path."""
    monkeypatch.setattr("app.analytics.service.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr("app.analytics.service.settings.duckdb_path", str(tmp_path / "test.duckdb"))


def test_current_status_endpoint_returns_empty_list_with_no_data(client) -> None:
    resp = client.get("/analytics/current-status")
    assert resp.status_code == 200
    assert resp.json() == []


def test_forecast_status_endpoint_requires_year_and_week(client) -> None:
    resp = client.get("/analytics/forecast-status")
    assert resp.status_code == 422

    resp = client.get("/analytics/forecast-status?year=2026&week=13")
    assert resp.status_code == 200
    assert resp.json() == []


def test_sector_metrics_endpoint_with_no_data(client) -> None:
    resp = client.get("/analytics/sector-metrics")
    assert resp.status_code == 200
    assert resp.json() == {"rows": [], "total": 0}


def test_congested_sectors_endpoint_with_no_data(client) -> None:
    resp = client.get("/analytics/congested-sectors")
    assert resp.status_code == 200
    assert resp.json() == {"rows": [], "total": 0}


def test_forecast_table_endpoint_with_filters(client) -> None:
    # region is harmless here even though forecast_results has no region
    # column — Filters.where_clause's available_columns restriction drops
    # it instead of raising a DuckDB BinderException.
    resp = client.get("/analytics/forecast-table?region=Central&year=2026")
    assert resp.status_code == 200
    assert resp.json() == {"rows": [], "total": 0}


def test_summary_endpoint_with_no_data(client) -> None:
    resp = client.get("/analytics/summary")
    assert resp.status_code == 200
    assert resp.json() == {"total_sectors": 0, "congested_count": 0, "avg_volume_gb": 0.0}


def test_filter_options_endpoint_with_no_data(client) -> None:
    resp = client.get("/analytics/filter-options")
    assert resp.status_code == 200
    assert resp.json() == {"regions": [], "years": [], "weeks": [], "operators": []}


def test_site_detail_endpoint_with_no_data(client) -> None:
    resp = client.get("/analytics/site-detail/SITE001")
    assert resp.status_code == 200
    assert resp.json() == {"site": None, "congested": False, "sectors": [], "forecast": [], "capex_upgrades": []}


def test_map_stats_endpoint_requires_bounds(client) -> None:
    resp = client.get("/analytics/map-stats")
    assert resp.status_code == 422

    resp = client.get("/analytics/map-stats?south=0&west=100&north=5&east=102")
    assert resp.status_code == 200
    assert resp.json() == {
        "total_sites": 0, "congested_sites": 0, "healthy_sites": 0,
        "coverage_holes": 0, "worst_coverage_hole": None, "total_capex": 0.0,
    }


def test_overview_stats_endpoint_with_no_data(client) -> None:
    resp = client.get("/analytics/overview-stats")
    assert resp.status_code == 200
    assert resp.json() == {
        "total_sites": 0, "total_congested_sites": 0, "total_capex": 0.0,
        "worst_congested_sector": None, "worst_ookla_cluster": None, "worst_mr_cluster": None,
    }


def test_site_forecast_endpoint_with_no_data(client) -> None:
    resp = client.get("/analytics/site-forecast/SITE001")
    assert resp.status_code == 200
    assert resp.json() == {"site_id": "SITE001", "metric": "eric_prb_util_rate", "actual": [], "forecast": []}


def test_site_forecast_endpoint_rejects_invalid_metric(client) -> None:
    resp = client.get("/analytics/site-forecast/SITE001?metric=bogus")
    assert resp.status_code == 400


def test_site_forecast_endpoint_rejects_invalid_horizon(client) -> None:
    resp = client.get("/analytics/site-forecast/SITE001?horizon_weeks=0")
    assert resp.status_code == 422


def test_site_coverage_endpoint_with_no_data(client) -> None:
    resp = client.get("/analytics/site-coverage", params={"south": 0, "west": 100, "north": 10, "east": 110})
    assert resp.status_code == 200
    assert resp.json() == []


def test_coverage_holes_by_band_endpoint_rejects_unknown_band(client) -> None:
    resp = client.get(
        "/analytics/coverage-holes-by-band",
        params={"south": 0, "west": 100, "north": 10, "east": 110, "band": "extreme"},
    )
    assert resp.status_code == 400


def test_geoserver_layers_endpoint_returns_empty_when_unreachable(client, monkeypatch) -> None:
    monkeypatch.setattr("app.analytics.service.settings.geoserver_url", "http://localhost:1")
    resp = client.get("/analytics/geoserver-layers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_nearby_geoserver_features_endpoint_returns_empty_when_unreachable(client, monkeypatch) -> None:
    monkeypatch.setattr("app.analytics.service.settings.geoserver_url", "http://localhost:1")
    resp = client.get("/analytics/nearby-geoserver-features", params={"layer": "substations", "lat": 3.1, "lng": 101.6})
    assert resp.status_code == 200
    assert resp.json() == []
