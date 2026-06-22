import duckdb

from app.ingestion.stages.pre_capex_upgrades import run


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingestion.stages.pre_capex_upgrades.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.ingestion.stages.pre_capex_upgrades.settings.duckdb_path", str(tmp_path / "test.duckdb")
    )


def _make_cell_reference(tmp_path, rows) -> str:
    con = duckdb.connect()
    ref_path = tmp_path / "cell_reference.parquet"
    values_sql = ", ".join(
        "(" + ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in row) + ")" for row in rows
    )
    con.execute(f"""
        COPY (SELECT * FROM (VALUES {values_sql}) AS t(cell_name, zoom_sector_id, avail_prb))
        TO '{ref_path}' (FORMAT PARQUET)
    """)
    return str(ref_path)


def _make_congestion(tmp_path, rows) -> str:
    con = duckdb.connect()
    cong_path = tmp_path / "congestion.parquet"
    values_sql = ", ".join(
        "(" + ", ".join(f"'{v}'" for v in row) + ")" for row in rows
    )
    con.execute(f"""
        COPY (SELECT * FROM (VALUES {values_sql}) AS t(zoom_sector_id, area_target))
        TO '{cong_path}' (FORMAT PARQUET)
    """)
    return str(cong_path)


def _read_output(output_path):
    cols = [d[0] for d in duckdb.connect().execute(f"DESCRIBE SELECT * FROM read_parquet('{output_path}')").fetchall()]
    return {r[0]: dict(zip(cols, r)) for r in duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchall()}


def test_xc_top4_per_cell_and_urban_divisor(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    ref_path = _make_cell_reference(tmp_path, [
        ("CELL_A", "SITE001_Macro_1", 50.0),
        ("CELL_B", "SITE001_Macro_1", 50.0),
    ])
    cong_path = _make_congestion(tmp_path, [("SITE001_Macro_1", "Urban")])

    raw = tmp_path / "raw_xc.csv"
    raw.write_text(
        "cell_name,bh_dl_rb_util_pct,user_count\n"
        # CELL_A: 5 rows, only top 4 by user_count should count -> rows with user 50,40,30,20 kept, user=1 dropped
        "CELL_A,80,50\nCELL_A,70,40\nCELL_A,60,30\nCELL_A,50,20\nCELL_A,10,1\n"
        "CELL_B,40,10\n"
    )

    output_path = run(str(raw), ref_path, cong_path, "xC")
    rows = _read_output(output_path)
    row = rows["SITE001_Macro_1"]

    # CELL_A top4 rb_used values (rate/100 * avail_prb=50): 40,35,30,25 -> mean = 32.5
    # CELL_B: only row rb_used = 0.4*50=20 -> mean = 20
    # sum_rb_used = 32.5 + 20 = 52.5
    assert row["sum_rb_used"] == 52.5
    assert row["sum_existing_prb"] == 100.0  # 50 + 50
    # urban divisor 0.8: 52.5/0.8 - 100 = 65.625 - 100 = -34.375
    assert abs(row["additional_rb"] - (52.5 / 0.8 - 100.0)) < 1e-9


def test_xd_direct_sum_no_top4(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    ref_path = _make_cell_reference(tmp_path, [("CELL_C", "SITE002_Macro_1", 30.0)])
    cong_path = _make_congestion(tmp_path, [("SITE002_Macro_1", "Rural")])

    raw = tmp_path / "raw_xd.csv"
    raw.write_text(
        "cell_name,eric_prb_utilzation_rate\n"
        "CELL_C,50\nCELL_C,60\n"
    )

    output_path = run(str(raw), ref_path, cong_path, "xD")
    row = _read_output(output_path)["SITE002_Macro_1"]

    # No top4/averaging for xD: sum of (rate/100*avail_prb) over ALL rows
    # (0.5*30) + (0.6*30) = 15 + 18 = 33
    assert row["sum_rb_used"] == 33.0
    # rural divisor 0.92: 33/0.92 - 30
    assert abs(row["additional_rb"] - (33.0 / 0.92 - 30.0)) < 1e-9


def test_only_congested_sectors_kept(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    ref_path = _make_cell_reference(tmp_path, [
        ("CELL_D", "SITE003_Macro_1", 10.0),
        ("CELL_E", "SITE004_Macro_1", 10.0),
    ])
    cong_path = _make_congestion(tmp_path, [("SITE003_Macro_1", "Urban")])  # SITE004 never congested

    raw = tmp_path / "raw_xd.csv"
    raw.write_text(
        "cell_name,eric_prb_utilzation_rate\nCELL_D,50\nCELL_E,50\n"
    )

    output_path = run(str(raw), ref_path, cong_path, "xD")
    rows = _read_output(output_path)
    assert list(rows.keys()) == ["SITE003_Macro_1"]


def test_bw_column_in_raw_file_overrides_reference_even_when_zero(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    ref_path = _make_cell_reference(tmp_path, [("CELL_F", "SITE005_Macro_1", 99.0)])
    cong_path = _make_congestion(tmp_path, [("SITE005_Macro_1", "Urban")])

    raw = tmp_path / "raw_xd.csv"
    raw.write_text(
        "cell_name,eric_prb_utilzation_rate,bw\nCELL_F,50,0\n"
    )

    output_path = run(str(raw), ref_path, cong_path, "xD")
    row = _read_output(output_path)["SITE005_Macro_1"]
    # bw=0 in raw file -> avail_prb=0*5=0, NOT the reference's 99.0
    assert row["sum_rb_used"] == 0.0
