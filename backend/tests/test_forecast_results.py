import duckdb

from app.ingestion.stages.forecast_results import run

COLUMNS = (
    "site_id", "zoom_sector_id", "week", "year", "region", "cluster", "ibc_macro",
    "f1f2f3", "eric_data_volume_ul_dl", "eric_prb_util_rate", "eric_dl_user_ip_thpt",
    "eric_max_rrc_user", "max_active_user", "dataset_type", "operator", "area_target",
    "bau_nic", "vendor",
)


def _row(zoom_sector_id, week, year, prb, thpt, volume=100.0, users=200, dataset_type="xC"):
    return (
        zoom_sector_id.split("_")[0], zoom_sector_id, week, year, "Central", "Unknown", "Macro",
        "f1", volume, prb, thpt, users, users, dataset_type, "Celcom", "Urban", "NIC", "Huawei",
    )


def _write_parquet(path, rows):
    con = duckdb.connect()
    values_sql = ", ".join(
        "(" + ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in row) + ")" for row in rows
    )
    cols_sql = ", ".join(COLUMNS)
    con.execute(f"COPY (SELECT * FROM (VALUES {values_sql}) AS t({cols_sql})) TO '{path}' (FORMAT PARQUET)")


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingestion.stages.forecast_results.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.ingestion.stages.forecast_results.settings.duckdb_path", str(tmp_path / "test.duckdb")
    )


def _read_output(output_path):
    cols = [d[0] for d in duckdb.connect().execute(f"DESCRIBE SELECT * FROM read_parquet('{output_path}')").fetchall()]
    return [dict(zip(cols, r)) for r in duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchall()]


def test_linear_regression_matches_closed_form(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    # x=1,2,3 -> prb = 10,20,30 (slope=10, intercept=0)
    _write_parquet(xc_path, [
        _row("SITE001_Macro_1", 1, 2026, prb=10, thpt=5),
        _row("SITE001_Macro_1", 2, 2026, prb=20, thpt=5),
        _row("SITE001_Macro_1", 3, 2026, prb=30, thpt=5),
    ])

    output_path = run([str(xc_path)], [])
    rows = sorted(_read_output(output_path), key=lambda r: (r["year"], r["week"]))

    # global_max = (2026, week 3) = this sector's own last point -> week_gap=0
    # first forecast offset=1 -> future_x = n_points(3) + 0 + 1 = 4
    # predicted_prb = 10*4 + 0 = 40
    first = rows[0]
    assert first["predicted_eric_prb_util_rate"] == 40.0
    assert len(rows) == 52


def test_sector_with_single_data_point_excluded(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    _write_parquet(xc_path, [
        _row("SITE002_Macro_1", 1, 2026, prb=50, thpt=5),  # only 1 point -> excluded
        _row("SITE003_Macro_1", 1, 2026, prb=10, thpt=5),
        _row("SITE003_Macro_1", 2, 2026, prb=20, thpt=5),
    ])

    output_path = run([str(xc_path)], [])
    zoom_ids = {r["zoom_sector_id"] for r in _read_output(output_path)}
    assert zoom_ids == {"SITE003_Macro_1"}


def test_all_weeks_congested_when_thresholds_persistently_met(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    # prb already high and rising (85,90,95) -> every future prediction >=80
    # thpt constant at 1 (<3), users constant 200 (>=120) -> always congested
    _write_parquet(xc_path, [
        _row("SITE004_Macro_1", 1, 2026, prb=85, thpt=1, users=200),
        _row("SITE004_Macro_1", 2, 2026, prb=90, thpt=1, users=200),
        _row("SITE004_Macro_1", 3, 2026, prb=95, thpt=1, users=200),
    ])

    output_path = run([str(xc_path)], [])
    rows = _read_output(output_path)

    assert all(r["congested"] for r in rows)
    assert all(r["forecast_congested_weeks"] == 52 for r in rows)
    assert all(r["month_congested"] for r in rows)


def test_never_congested_when_throughput_too_high(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    # prb high enough but thpt stays >=3 -> congestion condition never met
    _write_parquet(xc_path, [
        _row("SITE005_Macro_1", 1, 2026, prb=85, thpt=10, users=200),
        _row("SITE005_Macro_1", 2, 2026, prb=90, thpt=10, users=200),
        _row("SITE005_Macro_1", 3, 2026, prb=95, thpt=10, users=200),
    ])

    output_path = run([str(xc_path)], [])
    rows = _read_output(output_path)

    assert not any(r["congested"] for r in rows)
    assert all(r["forecast_congested_weeks"] == 0 for r in rows)
    assert not any(r["month_congested"] for r in rows)
