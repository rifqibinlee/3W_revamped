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


CONGESTION_COLUMNS = (
    "site_id", "zoom_sector_id", "region", "cluster", "operator", "congested",
    "eric_data_volume_ul_dl", "week", "year",
)


def _write_congestion_fixture(tmp_path, rows):
    _write_parquet(tmp_path / "congestion_analysis.parquet", rows, CONGESTION_COLUMNS)


def test_sector_metrics_returns_all_rows_unfiltered(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 10.0, 10, 2026),
        ("SITE002", "SITE002_Macro_1", "Southern", "C2", "Digi", False, 20.0, 10, 2026),
    ])
    rows = service.sector_metrics(service.Filters())
    assert len(rows) == 2


def test_sector_metrics_filters_by_region(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 10.0, 10, 2026),
        ("SITE002", "SITE002_Macro_1", "Southern", "C2", "Digi", False, 20.0, 10, 2026),
    ])
    rows = service.sector_metrics(service.Filters(region="Central"))
    assert len(rows) == 1
    assert rows[0]["region"] == "Central"


def test_sector_metrics_filter_rejects_sql_injection_attempt(tmp_path, monkeypatch) -> None:
    """region is bound as a parameter, not interpolated — a value designed
    to break out of a string literal should just match nothing, not error
    or alter the query."""
    _setup(tmp_path, monkeypatch)
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 10.0, 10, 2026),
    ])
    rows = service.sector_metrics(service.Filters(region="x' OR '1'='1"))
    assert rows == []


def test_congested_sectors_only_includes_congested(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 10.0, 10, 2026),
        ("SITE002", "SITE002_Macro_1", "Central", "C1", "Celcom", False, 20.0, 10, 2026),
    ])
    rows = service.congested_sectors(service.Filters())
    assert len(rows) == 1
    assert rows[0]["zoom_sector_id"] == "SITE001_Macro_1"


def test_congested_sectors_combines_with_other_filters(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 10.0, 10, 2026),
        ("SITE002", "SITE002_Macro_1", "Southern", "C2", "Celcom", True, 20.0, 10, 2026),
    ])
    rows = service.congested_sectors(service.Filters(region="Southern"))
    assert len(rows) == 1
    assert rows[0]["zoom_sector_id"] == "SITE002_Macro_1"


def test_forecast_table_filters_by_year(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_parquet(
        tmp_path / "forecast_results.parquet",
        [
            ("SITE001_Macro_1", "Central", 1, 2026),
            ("SITE001_Macro_1", "Central", 1, 2027),
        ],
        ("zoom_sector_id", "region", "week", "year"),
    )
    rows = service.forecast_table(service.Filters(year=2026))
    assert len(rows) == 1
    assert rows[0]["year"] == 2026


def test_summary_stats(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 10.0, 10, 2026),
        ("SITE002", "SITE002_Macro_1", "Central", "C1", "Celcom", False, 30.0, 10, 2026),
    ])
    stats = service.summary_stats(service.Filters())
    assert stats["total_sectors"] == 2
    assert stats["congested_count"] == 1
    assert stats["avg_volume_gb"] == 20.0


def test_summary_stats_empty_when_no_data(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    stats = service.summary_stats(service.Filters())
    assert stats == {"total_sectors": 0, "congested_count": 0, "avg_volume_gb": 0.0}


def test_site_detail_returns_empty_when_no_files(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    detail = service.site_detail("SITE001")
    assert detail == {"site": None, "congested": False, "sectors": [], "forecast": [], "capex_upgrades": []}


def test_site_detail_joins_site_sectors_and_forecast(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_parquet(
        tmp_path / "site_coordinates.parquet",
        [("SITE001", "Central", "C1", 3.1, 101.6)],
        ("site_id", "region", "cluster", "latitude", "longitude"),
    )
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", False, 10.0, 10, 2026),
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 12.0, 11, 2026),  # latest -> wins
        ("SITE002", "SITE002_Macro_1", "Southern", "C2", "Digi", True, 99.0, 11, 2026),  # different site
    ])
    _write_parquet(
        tmp_path / "forecast_results.parquet",
        [
            ("SITE001_Macro_1", "Central", 13, 2026),
            ("SITE002_Macro_1", "Southern", 13, 2026),
        ],
        ("zoom_sector_id", "region", "week", "year"),
    )

    detail = service.site_detail("site001")
    assert detail["site"]["site_id"] == "SITE001"
    assert detail["congested"] is True
    assert len(detail["sectors"]) == 1
    assert detail["sectors"][0]["week"] == 11
    assert len(detail["forecast"]) == 1
    assert detail["forecast"][0]["zoom_sector_id"] == "SITE001_Macro_1"
    assert detail["capex_upgrades"] == []


def test_site_detail_includes_capex_upgrades(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 10.0, 10, 2026),
    ])
    _write_parquet(
        tmp_path / "capex_upgrades_pre_capex.parquet",
        [("SITE001_Macro_1", "Case 3", 50000.0)],
        ("zoom_sector_id", "suggested_upgrade_case", "estimated_total_capex_rm"),
    )

    detail = service.site_detail("SITE001")
    assert len(detail["capex_upgrades"]) == 1
    assert detail["capex_upgrades"][0]["suggested_upgrade_case"] == "Case 3"


def test_filter_options_lists_distinct_values(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 10.0, 10, 2026),
        ("SITE002", "SITE002_Macro_1", "Southern", "C2", "Digi", False, 20.0, 11, 2026),
    ])
    options = service.filter_options()
    assert options["regions"] == ["Central", "Southern"]
    assert options["operators"] == ["Celcom", "Digi"]
    assert options["weeks"] == [10, 11]
    assert options["years"] == [2026]


def test_map_stats_returns_empty_when_no_data(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    stats = service.map_stats(south=0, west=100, north=5, east=102)
    assert stats == {
        "total_sites": 0, "congested_sites": 0, "healthy_sites": 0,
        "coverage_holes": 0, "worst_coverage_hole": None, "total_capex": 0.0,
    }


def test_map_stats_scopes_to_bounds(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_parquet(
        tmp_path / "site_coordinates.parquet",
        [
            ("SITE001", "Central", "C1", 3.1, 101.6),   # inside bbox
            ("SITE002", "Central", "C1", 3.2, 101.7),   # inside bbox
            ("SITE003", "Southern", "C2", 10.0, 110.0),  # outside bbox
        ],
        ("site_id", "region", "cluster", "latitude", "longitude"),
    )
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 10.0, 10, 2026),
        ("SITE002", "SITE002_Macro_1", "Central", "C1", "Celcom", False, 10.0, 10, 2026),
        ("SITE003", "SITE003_Macro_1", "Southern", "C2", "Celcom", True, 10.0, 10, 2026),
    ])
    _write_parquet(
        tmp_path / "capex_upgrades_pre_capex.parquet",
        [
            ("SITE001_Macro_1", "Case 3", 50000.0),
            ("SITE003_Macro_1", "Case 5", 99999.0),  # outside bbox, should be excluded
        ],
        ("zoom_sector_id", "suggested_upgrade_case", "estimated_total_capex_rm"),
    )

    stats = service.map_stats(south=3.0, west=101.0, north=3.5, east=102.0)
    assert stats["total_sites"] == 2
    assert stats["congested_sites"] == 1
    assert stats["healthy_sites"] == 1
    assert stats["total_capex"] == 50000.0


def test_map_stats_forecast_mode_uses_forecast_results(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_parquet(
        tmp_path / "site_coordinates.parquet",
        [("SITE001", "Central", "C1", 3.1, 101.6)],
        ("site_id", "region", "cluster", "latitude", "longitude"),
    )
    _write_parquet(
        tmp_path / "forecast_results.parquet",
        [("SITE001_Macro_1", True, "Central", 13, 2026)],
        ("zoom_sector_id", "congested", "region", "week", "year"),
    )

    stats = service.map_stats(south=3.0, west=101.0, north=3.5, east=102.0, year=2026, week=13)
    assert stats["total_sites"] == 1
    assert stats["congested_sites"] == 1


def test_map_stats_worst_coverage_hole_within_bounds(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_parquet(
        tmp_path / "site_coordinates.parquet",
        [("SITE001", "Central", "C1", 3.1, 101.6)],
        ("site_id", "region", "cluster", "latitude", "longitude"),
    )
    _write_parquet(
        tmp_path / "coverage_holes.parquet",
        [
            (3.10, 101.60, -115.0, "CELL_A", "MR", 0),
            (3.11, 101.61, -116.0, "CELL_A", "MR", 0),
            (3.12, 101.62, -117.0, "CELL_A", "MR", 0),
            (3.13, 101.63, -112.0, "CELL_B", "Ookla", 1),
            (10.0, 110.0, -118.0, "CELL_C", "MR", 2),  # outside bbox
        ],
        ("latitude", "longitude", "signal_strength", "serving_cell", "data_source", "cluster_id"),
    )

    stats = service.map_stats(south=3.0, west=101.0, north=3.5, east=102.0)
    assert stats["coverage_holes"] == 2
    assert stats["worst_coverage_hole"]["cluster_id"] == 0
    assert stats["worst_coverage_hole"]["point_count"] == 3
    assert stats["worst_coverage_hole"]["data_source"] == "MR"


def test_overview_stats_returns_empty_when_no_data(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    stats = service.overview_stats()
    assert stats == {
        "total_sites": 0, "total_congested_sites": 0, "total_capex": 0.0,
        "worst_ookla_cluster": None, "worst_mr_cluster": None,
    }


def test_overview_stats_aggregates_network_wide(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    _write_congestion_fixture(tmp_path, [
        ("SITE001", "SITE001_Macro_1", "Central", "C1", "Celcom", True, 10.0, 10, 2026),
        ("SITE002", "SITE002_Macro_1", "Southern", "C2", "Digi", False, 20.0, 10, 2026),
    ])
    _write_parquet(
        tmp_path / "capex_upgrades_pre_capex.parquet",
        [("SITE001_Macro_1", "Case 3", 50000.0)],
        ("zoom_sector_id", "suggested_upgrade_case", "estimated_total_capex_rm"),
    )
    _write_parquet(
        tmp_path / "coverage_holes.parquet",
        [
            (3.10, 101.60, -115.0, "CELL_A", "Ookla", 0),
            (3.11, 101.61, -116.0, "CELL_A", "Ookla", 0),
            (3.50, 102.00, -112.0, "CELL_B", "MR", 5),
        ],
        ("latitude", "longitude", "signal_strength", "serving_cell", "data_source", "cluster_id"),
    )

    stats = service.overview_stats()
    assert stats["total_sites"] == 2
    assert stats["total_congested_sites"] == 1
    assert stats["total_capex"] == 50000.0
    assert stats["worst_ookla_cluster"] == {"cluster_id": 0, "data_source": "Ookla", "point_count": 2, "avg_signal": -115.5}
    assert stats["worst_mr_cluster"] == {"cluster_id": 5, "data_source": "MR", "point_count": 1, "avg_signal": -112.0}
