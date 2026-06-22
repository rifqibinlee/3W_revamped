import duckdb

from app.ingestion.stages.xd_zte import run


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingestion.stages.xd_zte.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr("app.ingestion.stages.xd_zte.settings.duckdb_path", str(tmp_path / "test.duckdb"))


def _make_cell_reference(tmp_path) -> str:
    con = duckdb.connect()
    ref_path = tmp_path / "cell_reference.parquet"
    con.execute(f"""
        COPY (
            SELECT * FROM (VALUES
                ('SITE001_DLD_2', 50.0, 'Urban', 'NIC'),
                ('SITE001_CMM_2', 30.0, 'Urban', 'NIC')
            ) AS t(cell_name, avail_prb, area_target, bau_nic)
        ) TO '{ref_path}' (FORMAT PARQUET)
    """)
    return str(ref_path)


def _output_rows(output_path):
    cols = [d[0] for d in duckdb.connect().execute(f"DESCRIBE SELECT * FROM read_parquet('{output_path}')").fetchall()]
    return {r[cols.index("zoom_sector_id")]: dict(zip(cols, r)) for r in
            duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchall()}


def test_prb_util_from_avail_prb_join_and_band_rollup(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    ref_path = _make_cell_reference(tmp_path)

    raw = tmp_path / "weekly.csv"
    raw.write_text(
        "cell_name,week,year,region,eric_prb_util_rate,eric_data_volume_ul_dl,"
        "eric_dl_user_ip_thpt,max_active_user\n"
        "SITE001_DLD_2,10,2026,Central,80,10,5,50\n"
        "SITE001_CMM_2,10,2026,Central,40,20,3,30\n"
    )

    output_path = run(str(raw), ref_path)
    rows = _output_rows(output_path)

    assert list(rows.keys()) == ["SITE001_Macro_2"]
    row = rows["SITE001_Macro_2"]

    # prb_used = rate/100*avail_prb -> (0.8*50)+(0.4*30) = 40+12 = 52
    # sum_A (avail_prb) = 50+30 = 80 -> 52/80*100 = 65.0
    assert row["eric_prb_util_rate"] == 65.0
    assert row["eric_data_volume_ul_dl"] == 30.0
    assert row["eric_max_rrc_user"] == 80
    assert row["f1f2f3"] == "f1f2"
    assert row["area_target"] == "Urban"
    assert row["dataset_type"] == "xD"


def test_volume_and_throughput_unit_safeguard_divides_by_1000(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    ref_path = _make_cell_reference(tmp_path)

    raw = tmp_path / "weekly.csv"
    raw.write_text(
        "cell_name,week,year,eric_prb_util_rate,eric_data_volume_ul_dl,"
        "eric_dl_user_ip_thpt,max_active_user\n"
        "SITE002_DLD_1,10,2026,50,5000,8000,10\n"
    )

    output_path = run(str(raw), ref_path)
    row = next(iter(_output_rows(output_path).values()))

    assert row["eric_data_volume_ul_dl"] == 5.0  # 5000 / 1000
    assert row["eric_dl_user_ip_thpt"] == 8.0  # 8000 / 1000


def test_hyphen_delimited_cell_name_classified_as_digi(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    ref_path = _make_cell_reference(tmp_path)

    raw = tmp_path / "weekly.csv"
    raw.write_text(
        "cell_name,week,year,eric_prb_util_rate,eric_data_volume_ul_dl,"
        "eric_dl_user_ip_thpt,max_active_user\n"
        "SITE003-DLD-1,10,2026,50,1,1,5\n"
    )

    output_path = run(str(raw), ref_path)
    row = next(iter(_output_rows(output_path).values()))

    assert row["operator"] == "Digi"
    assert row["zoom_sector_id"] == "SITE003_Macro_1"
