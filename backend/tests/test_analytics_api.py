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
