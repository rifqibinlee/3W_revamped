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
    assert resp.json() == []


def test_congested_sectors_endpoint_with_no_data(client) -> None:
    resp = client.get("/analytics/congested-sectors")
    assert resp.status_code == 200
    assert resp.json() == []


def test_forecast_table_endpoint_with_filters(client) -> None:
    resp = client.get("/analytics/forecast-table?region=Central&year=2026")
    assert resp.status_code == 200
    assert resp.json() == []


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
        "worst_ookla_cluster": None, "worst_mr_cluster": None,
    }
