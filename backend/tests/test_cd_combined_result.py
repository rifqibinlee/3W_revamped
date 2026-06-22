import duckdb

from app.ingestion.stages.cd_combined_result import run

SECTOR_COLUMNS = (
    "site_id", "zoom_sector_id", "week", "year", "region", "cluster", "ibc_macro",
    "f1f2f3", "eric_data_volume_ul_dl", "eric_prb_util_rate", "eric_dl_user_ip_thpt",
    "eric_max_rrc_user", "max_active_user", "dataset_type", "operator", "area_target",
    "bau_nic", "vendor",
)

CONGESTION_COLUMNS = SECTOR_COLUMNS + ("month", "congested", "congested_weeks", "congested_count_month")


def _sector_row(zoom_sector_id, week=1, year=2026, region="Central", area_target="Urban", bau_nic="NIC"):
    return (
        zoom_sector_id.split("_")[0], zoom_sector_id, week, year, region, "Unknown", "Macro",
        "f1", 10.0, 85.0, 6.0, 10, 10, "xC", "Celcom", area_target, bau_nic, "Huawei",
    )


def _congestion_row(zoom_sector_id, week=1, year=2026, congested=True, congested_weeks=1,
                     region="Central", area_target="Urban", bau_nic="NIC"):
    base = _sector_row(zoom_sector_id, week, year, region, area_target, bau_nic)
    return base + (1, congested, congested_weeks, 1 if congested else 0)


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


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingestion.stages.cd_combined_result.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.ingestion.stages.cd_combined_result.settings.duckdb_path", str(tmp_path / "test.duckdb")
    )


def test_short_sector_id_and_congested_join(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    _write_parquet(xc_path, [_sector_row("SITE001_Macro_1")], SECTOR_COLUMNS)

    cong_path = tmp_path / "congestion.parquet"
    _write_parquet(cong_path, [_congestion_row("SITE001_Macro_1", congested=True, congested_weeks=3)], CONGESTION_COLUMNS)

    outputs = run([str(xc_path)], [], str(cong_path))
    cd_rows = duckdb.connect().execute(
        f"SELECT * FROM read_csv('{outputs['cd_combined']}')"
    ).fetchdf().to_dict("records")

    assert len(cd_rows) == 1
    row = cd_rows[0]
    assert row["short_sector_id"] == "SITE001_M_1"
    assert row["is_congested"] is True or row["is_congested"] == 1
    assert row["congested_weeks"] == 3


def test_sector_filtered_by_congestion_analysis_still_appears_in_metrics(tmp_path, monkeypatch) -> None:
    """A sector with region='Unknown' would have been dropped by
    congestion_analysis's filters, so it has no congestion row — but it
    must still appear in Sector_Metrics (unfiltered) and in CD_Combined
    with congested defaulted to false/0."""
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    _write_parquet(xc_path, [_sector_row("SITE002_Macro_1", region="Unknown")], SECTOR_COLUMNS)

    cong_path = tmp_path / "congestion.parquet"
    _write_parquet(cong_path, [_congestion_row("SITE003_Macro_1")], CONGESTION_COLUMNS)

    outputs = run([str(xc_path)], [], str(cong_path))

    sector_rows = duckdb.connect().execute(f"SELECT * FROM read_csv('{outputs['sector_metrics']}')").fetchdf()
    assert "SITE002_Macro_1" in sector_rows["zoom_sector_id"].tolist()

    cd_rows = duckdb.connect().execute(f"SELECT * FROM read_csv('{outputs['cd_combined']}')").fetchdf()
    site002 = cd_rows[cd_rows["zoom_sector_id"] == "SITE002_Macro_1"].iloc[0]
    assert site002["congested_weeks"] == 0
    assert site002["is_congested"] in (False, 0)


def test_congested_sectors_csv_only_includes_congested_rows(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    xc_path = tmp_path / "xc.parquet"
    _write_parquet(xc_path, [_sector_row("SITE004_Macro_1")], SECTOR_COLUMNS)

    cong_path = tmp_path / "congestion.parquet"
    _write_parquet(
        cong_path,
        [
            _congestion_row("SITE004_Macro_1", congested=True),
            _congestion_row("SITE005_Macro_1", congested=False, congested_weeks=0),
        ],
        CONGESTION_COLUMNS,
    )

    outputs = run([str(xc_path)], [], str(cong_path))
    congested_rows = duckdb.connect().execute(f"SELECT * FROM read_csv('{outputs['congested_sectors']}')").fetchdf()

    assert congested_rows["zoom_sector_id"].tolist() == ["SITE004_Macro_1"]
