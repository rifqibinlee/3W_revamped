import duckdb

from app.ingestion.stages.congestion_analysis import run

COLUMNS = (
    "site_id", "zoom_sector_id", "week", "year", "region", "cluster", "ibc_macro",
    "f1f2f3", "eric_data_volume_ul_dl", "eric_prb_util_rate", "eric_dl_user_ip_thpt",
    "eric_max_rrc_user", "max_active_user", "dataset_type", "operator", "area_target",
    "bau_nic", "vendor",
)


def _row(zoom_sector_id, week, year, prb, thpt, area_target="Urban", bau_nic="NIC",
         region="Central", volume=10.0, dataset_type="xC"):
    return (
        zoom_sector_id.split("_")[0], zoom_sector_id, week, year, region, "Unknown", "Macro",
        "f1", volume, prb, thpt, 10, 10, dataset_type, "Celcom", area_target, bau_nic, "Huawei",
    )


def _write_parquet(path, rows):
    con = duckdb.connect()
    values_sql = ", ".join(
        "(" + ", ".join(
            f"'{v}'" if isinstance(v, str) else str(v) for v in row
        ) + ")"
        for row in rows
    )
    cols_sql = ", ".join(COLUMNS)
    con.execute(f"""
        COPY (SELECT * FROM (VALUES {values_sql}) AS t({cols_sql}))
        TO '{path}' (FORMAT PARQUET)
    """)


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingestion.stages.congestion_analysis.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.ingestion.stages.congestion_analysis.settings.duckdb_path", str(tmp_path / "test.duckdb")
    )


def _read_output(output_path):
    cols = [d[0] for d in duckdb.connect().execute(f"DESCRIBE SELECT * FROM read_parquet('{output_path}')").fetchall()]
    return [dict(zip(cols, r)) for r in duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchall()]


def test_urban_nic_threshold(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    _write_parquet(xc_path, [
        _row("SITE001_Macro_1", 1, 2026, prb=85, thpt=6, area_target="Urban", bau_nic="NIC"),  # congested
        _row("SITE002_Macro_1", 1, 2026, prb=85, thpt=8, area_target="Urban", bau_nic="NIC"),  # not (thpt too high)
    ])
    output_path = run([str(xc_path)], [])
    rows = {r["zoom_sector_id"]: r for r in _read_output(output_path)}
    assert rows["SITE001_Macro_1"]["congested"] is True
    assert rows["SITE002_Macro_1"]["congested"] is False


def test_urban_non_nic_threshold(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    _write_parquet(xc_path, [
        _row("SITE003_Macro_1", 1, 2026, prb=85, thpt=4, area_target="Urban", bau_nic="BAU"),  # congested (<5)
        _row("SITE004_Macro_1", 1, 2026, prb=85, thpt=6, area_target="Urban", bau_nic="BAU"),  # not (needs <5)
    ])
    output_path = run([str(xc_path)], [])
    rows = {r["zoom_sector_id"]: r for r in _read_output(output_path)}
    assert rows["SITE003_Macro_1"]["congested"] is True
    assert rows["SITE004_Macro_1"]["congested"] is False


def test_rural_threshold(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    _write_parquet(xc_path, [
        _row("SITE005_Macro_1", 1, 2026, prb=93, thpt=2, area_target="Rural", bau_nic="BAU"),  # congested
        _row("SITE006_Macro_1", 1, 2026, prb=85, thpt=2, area_target="Rural", bau_nic="BAU"),  # not (needs >=92)
    ])
    output_path = run([str(xc_path)], [])
    rows = {r["zoom_sector_id"]: r for r in _read_output(output_path)}
    assert rows["SITE005_Macro_1"]["congested"] is True
    assert rows["SITE006_Macro_1"]["congested"] is False


def test_unknown_region_dropped(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    _write_parquet(xc_path, [
        _row("SITE007_Macro_1", 1, 2026, prb=85, thpt=6, region="Unknown"),
        _row("SITE008_Macro_1", 1, 2026, prb=85, thpt=6, region="Central"),
    ])
    output_path = run([str(xc_path)], [])
    zoom_ids = {r["zoom_sector_id"] for r in _read_output(output_path)}
    assert zoom_ids == {"SITE008_Macro_1"}


def test_all_zero_metrics_dropped(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    _write_parquet(xc_path, [
        _row("SITE009_Macro_1", 1, 2026, prb=0, thpt=0, volume=0.0),
        _row("SITE010_Macro_1", 1, 2026, prb=0, thpt=0, volume=5.0),  # has volume, not dropped
    ])
    output_path = run([str(xc_path)], [])
    zoom_ids = {r["zoom_sector_id"] for r in _read_output(output_path)}
    assert zoom_ids == {"SITE010_Macro_1"}


def test_congested_weeks_cumulative_and_month_rollup(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    # Weeks 1-4 fall in month 1 per the legacy formula. Congested in weeks 1, 2, 4.
    _write_parquet(xc_path, [
        _row("SITE011_Macro_1", 1, 2026, prb=85, thpt=6),  # congested
        _row("SITE011_Macro_1", 2, 2026, prb=85, thpt=6),  # congested
        _row("SITE011_Macro_1", 3, 2026, prb=10, thpt=20),  # not congested
        _row("SITE011_Macro_1", 4, 2026, prb=85, thpt=6),  # congested
    ])
    output_path = run([str(xc_path)], [])
    rows = {r["week"]: r for r in _read_output(output_path)}

    assert rows[1]["congested_weeks"] == 1
    assert rows[2]["congested_weeks"] == 2
    assert rows[3]["congested_weeks"] == 2  # not congested, cumulative unchanged
    assert rows[4]["congested_weeks"] == 3
    assert all(rows[w]["congested_count_month"] == 3 for w in (1, 2, 3, 4))  # all in month 1
