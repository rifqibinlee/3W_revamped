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
