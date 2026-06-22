import duckdb

from app.analytics import service


def _write_parquet(path, rows, columns):
    con = duckdb.connect()
    values_sql = ", ".join(
        "(" + ", ".join(
            ("true" if v is True else "false" if v is False else "NULL" if v is None
             else f"'{v}'" if isinstance(v, str) else str(v))
            for v in row
        ) + ")"
        for row in rows
    )
    cols_sql = ", ".join(columns)
    con.execute(f"COPY (SELECT * FROM (VALUES {values_sql}) AS t({cols_sql})) TO '{path}' (FORMAT PARQUET)")


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.analytics.service.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr("app.analytics.service.settings.duckdb_path", str(tmp_path / "test.duckdb"))


def test_current_status_picks_latest_week_per_sector(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_parquet(
        tmp_path / "congestion_analysis.parquet",
        [
            ("SITE001", "SITE001_Macro_1", "Central", False, 10, 2026),
            ("SITE001", "SITE001_Macro_1", "Central", True, 11, 2026),  # latest -> should win
        ],
        ("site_id", "zoom_sector_id", "region", "congested", "week", "year"),
    )
    _write_parquet(
        tmp_path / "site_coordinates.parquet",
        [("SITE001", "Central", "Unknown", 3.1, 101.6)],
        ("site_id", "region", "cluster", "latitude", "longitude"),
    )

    rows = service.current_status()
    assert len(rows) == 1
    assert rows[0]["congested"] is True
    assert rows[0]["latitude"] == 3.1


def test_current_status_returns_empty_when_files_missing(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    assert service.current_status() == []


def test_forecast_status_filters_by_year_and_week(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_parquet(
        tmp_path / "forecast_results.parquet",
        [
            ("SITE002_Macro_1", True, "Central", 13, 2026),
            ("SITE002_Macro_1", False, "Central", 26, 2026),
        ],
        ("zoom_sector_id", "congested", "region", "week", "year"),
    )
    _write_parquet(
        tmp_path / "site_coordinates.parquet",
        [("SITE002", "Central", "Unknown", 4.2, 102.1)],
        ("site_id", "region", "cluster", "latitude", "longitude"),
    )

    rows_w13 = service.forecast_status(2026, 13)
    assert len(rows_w13) == 1
    assert rows_w13[0]["congested"] is True
    assert rows_w13[0]["longitude"] == 102.1

    rows_w26 = service.forecast_status(2026, 26)
    assert rows_w26[0]["congested"] is False
