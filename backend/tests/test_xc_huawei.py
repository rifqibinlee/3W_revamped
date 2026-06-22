import duckdb

from app.ingestion.stages.xc_huawei import run


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingestion.stages.xc_huawei.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr("app.ingestion.stages.xc_huawei.settings.duckdb_path", str(tmp_path / "test.duckdb"))


def _make_cell_reference(tmp_path) -> str:
    """Minimal cell_reference fixture: SITE001_DLD_2 matches by join_key
    directly; SITE001_CMM_2 has no direct match and falls back to the
    site_id-level reference row."""
    con = duckdb.connect()
    ref_path = tmp_path / "cell_reference.parquet"
    con.execute(f"""
        COPY (
            SELECT * FROM (VALUES
                ('SITE001_DLD_2', 'SITE001DLD2', 'SITE001', 'Urban', 'NIC'),
                ('SITE001_OTHER', 'SITE001OTHER', 'SITE001', 'Suburb', 'BAU')
            ) AS t(cell_name, join_key, site_id, area_target, bau_nic)
        ) TO '{ref_path}' (FORMAT PARQUET)
    """)
    return str(ref_path)


def test_two_band_rollup_and_reference_join(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    ref_path = _make_cell_reference(tmp_path)

    raw = tmp_path / "weekly.csv"
    raw.write_text(
        "cell_name,band,week,year,region,dl_prb_num,dl_prb_denom,"
        "user_dl_thp_num,user_dl_thp_denom,data_volume,eric_max_rrc_user\n"
        "SITE001_DLD_2,L18,10,2025,Central,80,100,500,100,10,50\n"
        "SITE001_CMM_2,L9,10,2025,Central,20,100,200,100,20,30\n"
    )

    output_path = run(str(raw), ref_path)
    rows = {
        r[1]: dict(zip([d[0] for d in duckdb.connect().execute(
            f"DESCRIBE SELECT * FROM read_parquet('{output_path}')").fetchall()], r))
        for r in duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchall()
    }

    assert list(rows.keys()) == ["SITE001_Macro_2"]
    row = rows["SITE001_Macro_2"]

    assert row["eric_prb_util_rate"] == 50.0  # (80+20)/(100+100)*100
    assert row["eric_dl_user_ip_thpt"] == (700 / 200) / 1000.0
    assert row["eric_data_volume_ul_dl"] == 30.0  # 10 + 20
    assert row["eric_max_rrc_user"] == 80  # 50 + 30
    assert row["f1f2f3"] == "f1f2"  # DLD -> F1, CMM -> F2
    assert row["area_target"] == "Urban"  # joined via join_key on SITE001_DLD_2
    assert row["dataset_type"] == "xC"


def test_top4_selection_keeps_only_busiest_rows(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    ref_path = _make_cell_reference(tmp_path)

    rows = ["cell_name,band,week,year,dl_prb_num,dl_prb_denom,eric_max_rrc_user"]
    # 5 rows for the same (cell, band, week, year) — only top 4 by
    # eric_max_rrc_user should survive, so dl_prb_num sums to 10+20+30+40=100,
    # excluding the busiest-last row (user=1, prb_num=99) which ranks lowest.
    for users, prb_num in [(50, 10), (40, 20), (30, 30), (20, 40), (1, 99)]:
        rows.append(f"SITE002_DLD_1,L18,10,2025,{prb_num},100,{users}")

    raw = tmp_path / "weekly.csv"
    raw.write_text("\n".join(rows) + "\n")

    output_path = run(str(raw), ref_path)
    row = duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchone()
    cols = [d[0] for d in duckdb.connect().execute(f"DESCRIBE SELECT * FROM read_parquet('{output_path}')").fetchall()]
    result = dict(zip(cols, row))

    # sum(dl_prb_num) over kept top-4 rows / sum(dl_prb_denom over same 4) * 100
    assert result["eric_prb_util_rate"] == 25.0  # (10+20+30+40)/(400)*100
