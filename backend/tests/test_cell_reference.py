import duckdb

from app.ingestion.stages.cell_reference import run


def _run_csv(tmp_path, monkeypatch, header: str, rows: list[str]):
    monkeypatch.setattr("app.ingestion.stages.cell_reference.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.ingestion.stages.cell_reference.settings.duckdb_path", str(tmp_path / "test.duckdb")
    )
    raw = tmp_path / "reference.csv"
    raw.write_text(header + "\n" + "\n".join(rows) + "\n")
    output_path = run([str(raw)])
    rows_out = duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchall()
    cols = [
        d[0]
        for d in duckdb.connect().execute(f"DESCRIBE SELECT * FROM read_parquet('{output_path}')").fetchall()
    ]
    return {r[cols.index("cell_name")]: dict(zip(cols, r)) for r in rows_out}


def test_site_and_sector_parsing_underscore_delimited(tmp_path, monkeypatch) -> None:
    result = _run_csv(
        tmp_path,
        monkeypatch,
        "cell_name,band,xtxr,bw",
        ["SITE001_DLD_2,L18,4T4R,20"],
    )
    row = result["SITE001_DLD_2"]
    assert row["site_id"] == "SITE001"
    assert row["sector_suffix"] == "2"
    assert row["zoom_sector_id"] == "SITE001_Macro_2"
    assert row["avail_prb"] == 100.0  # 20 * 5.0


def test_inbuilding_and_pbts_classification(tmp_path, monkeypatch) -> None:
    result = _run_csv(
        tmp_path,
        monkeypatch,
        "cell_name,band,xtxr,bw",
        ["SITE002_BL_1,L9,2T2R,10", "SITE003_PL_1,L9,2T2R,10"],
    )
    assert result["SITE002_BL_1"]["ibc_macro"] == "Inbuilding"
    assert result["SITE003_PL_1"]["ibc_macro"] == "PBTS"


def test_f1f2f3_classification_branches(tmp_path, monkeypatch) -> None:
    result = _run_csv(
        tmp_path,
        monkeypatch,
        "cell_name,band,xtxr,bw",
        [
            "123,L18,4T4R,20",  # bare 2-3 digit -> F1
            "SITE_12_3,L18,4T4R,20",  # _NN_N$ -> F3
            "SITE_BLC_1,L18,4T4R,20",  # BLC -> F2
            "SITE_DLD_1,L18,4T4R,20",  # DLD -> F1
        ],
    )
    assert result["123"]["f1f2f3"] == "F1"
    assert result["SITE_12_3"]["f1f2f3"] == "F3"
    assert result["SITE_BLC_1"]["f1f2f3"] == "F2"
    assert result["SITE_DLD_1"]["f1f2f3"] == "F1"


def test_band_falls_back_to_cell_name_when_no_band_column(tmp_path, monkeypatch) -> None:
    result = _run_csv(
        tmp_path,
        monkeypatch,
        "cell_name,xtxr,bw",
        ["SITE004_DL1800_1,4T4R,20"],
    )
    assert result["SITE004_DL1800_1"]["band"] == "L18"


def test_area_target_bau_nic_and_join_key(tmp_path, monkeypatch) -> None:
    result = _run_csv(
        tmp_path,
        monkeypatch,
        "cell_name,band,xtxr,bw,urban_target,bau_nic_flag",
        ["SITE-005_DLD_1,L18,4T4R,20,Urban,NIC", "SITE006_DLD_1,L18,4T4R,20,,"],
    )
    row = result["SITE-005_DLD_1"]
    assert row["area_target"] == "Urban"
    assert row["bau_nic"] == "NIC"
    assert row["join_key"] == "SITE005DLD1"

    row_empty = result["SITE006_DLD_1"]
    assert row_empty["area_target"] is None
    assert row_empty["bau_nic"] is None
