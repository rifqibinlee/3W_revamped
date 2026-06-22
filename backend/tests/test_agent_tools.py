import duckdb

from app.agent.tools import get_capex_pricing, get_current_congestion_status, get_forecast_status
from app.ingestion.capex_solver import DEFAULT_PRICING


def _write_parquet(path, rows, columns):
    con = duckdb.connect()
    values_sql = ", ".join(
        "(" + ", ".join(
            ("true" if v is True else "false" if v is False else f"'{v}'" if isinstance(v, str) else str(v))
            for v in row
        ) + ")"
        for row in rows
    )
    cols_sql = ", ".join(columns)
    con.execute(f"COPY (SELECT * FROM (VALUES {values_sql}) AS t({cols_sql})) TO '{path}' (FORMAT PARQUET)")


def test_get_current_congestion_status_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.analytics.service.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr("app.analytics.service.settings.duckdb_path", str(tmp_path / "test.duckdb"))
    _write_parquet(
        tmp_path / "congestion_analysis.parquet",
        [("SITE001", "SITE001_Macro_1", "Central", True, 10, 2026)],
        ("site_id", "zoom_sector_id", "region", "congested", "week", "year"),
    )
    _write_parquet(
        tmp_path / "site_coordinates.parquet",
        [("SITE001", "Central", "Unknown", 3.1, 101.6)],
        ("site_id", "region", "cluster", "latitude", "longitude"),
    )

    result = get_current_congestion_status.invoke({"zoom_sector_id": "SITE001_Macro_1"})
    assert result["congested"] is True


def test_get_current_congestion_status_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.analytics.service.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr("app.analytics.service.settings.duckdb_path", str(tmp_path / "test.duckdb"))

    result = get_current_congestion_status.invoke({"zoom_sector_id": "NONEXISTENT"})
    assert "error" in result


def test_get_forecast_status_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.analytics.service.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr("app.analytics.service.settings.duckdb_path", str(tmp_path / "test.duckdb"))
    _write_parquet(
        tmp_path / "forecast_results.parquet",
        [("SITE002_Macro_1", False, "Central", 13, 2026)],
        ("zoom_sector_id", "congested", "region", "week", "year"),
    )
    _write_parquet(
        tmp_path / "site_coordinates.parquet",
        [("SITE002", "Central", "Unknown", 4.2, 102.1)],
        ("site_id", "region", "cluster", "latitude", "longitude"),
    )

    result = get_forecast_status.invoke({"zoom_sector_id": "SITE002_Macro_1", "year": 2026, "week": 13})
    assert result["congested"] is False


def test_get_capex_pricing_falls_back_to_defaults(db_session, monkeypatch) -> None:
    # The tool calls SessionLocal() itself (consistent with the rest of the
    # codebase opening its own DB connection per call) rather than taking
    # an injected session — so the test patches the name in tools' own
    # module namespace to return the shared db_session fixture instead.
    monkeypatch.setattr("app.agent.tools.SessionLocal", lambda: db_session)
    result = get_capex_pricing.invoke({})
    assert result == DEFAULT_PRICING
