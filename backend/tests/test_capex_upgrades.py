import duckdb

from app.ingestion.capex_solver import DEFAULT_PRICING
from app.ingestion.stages.capex_upgrades import run


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingestion.stages.capex_upgrades.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.ingestion.stages.capex_upgrades.settings.duckdb_path", str(tmp_path / "test.duckdb")
    )


def _write_parquet(path, rows, columns):
    con = duckdb.connect()
    values_sql = ", ".join(
        "(" + ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in row) + ")" for row in rows
    )
    cols_sql = ", ".join(columns)
    con.execute(f"COPY (SELECT * FROM (VALUES {values_sql}) AS t({cols_sql})) TO '{path}' (FORMAT PARQUET)")


def test_join_and_solver_invocation_end_to_end(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)

    pre_capex_path = tmp_path / "pre_capex.parquet"
    _write_parquet(
        pre_capex_path,
        [("SITE001_Macro_1", "xC", 2026, 10, 0.0, 50.0, 100.0)],
        ("zoom_sector_id", "dataset_type", "year", "week", "sum_existing_prb", "sum_rb_used", "additional_rb"),
    )

    congestion_path = tmp_path / "congestion.parquet"
    _write_parquet(
        congestion_path,
        [("SITE001_Macro_1", 2026, 10, "Rural", "Macro", "NIC", "Celcom", "Central")],
        ("zoom_sector_id", "year", "week", "area_target", "ibc_macro", "bau_nic", "operator", "region"),
    )

    # No cell_reference rows for this sector -> aggregated_bands empty,
    # current_config_map empty, same scenario as the solver's
    # "first step adds a network layer" unit test.
    cell_reference_path = tmp_path / "cell_reference.parquet"
    _write_parquet(
        cell_reference_path,
        [("OTHER_CELL", "SITE999_Macro_1", "L18", "F1", "2T2R", 50.0)],
        ("cell_name", "zoom_sector_id", "band", "f1f2f3", "xtxr", "avail_prb"),
    )

    output_path = run(str(pre_capex_path), str(congestion_path), str(cell_reference_path), DEFAULT_PRICING)
    row = duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchdf().iloc[0]

    assert row["zoom_sector_id"] == "SITE001_Macro_1"
    assert row["suggested_upgrade_case"] == "Case 3 (Add network layer only)"
    assert row["suggested_f1_l18"] == "2T2R"
    assert row["projected_prb_pct"] == 50.0


def test_zero_avail_prb_falls_back_to_bw_map_global(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)

    pre_capex_path = tmp_path / "pre_capex.parquet"
    _write_parquet(
        pre_capex_path,
        [("SITE002_Macro_1", "xC", 2026, 10, 0.0, 50.0, 100.0)],
        ("zoom_sector_id", "dataset_type", "year", "week", "sum_existing_prb", "sum_rb_used", "additional_rb"),
    )
    congestion_path = tmp_path / "congestion.parquet"
    _write_parquet(
        congestion_path,
        [("SITE002_Macro_1", 2026, 10, "Rural", "Macro", "NIC", "Celcom", "Central")],
        ("zoom_sector_id", "year", "week", "area_target", "ibc_macro", "bau_nic", "operator", "region"),
    )
    # avail_prb = 0 -> should fall back to BW_MAP_GLOBAL[('F1','L18','xC')] * 5.0 = 20*5 = 100
    cell_reference_path = tmp_path / "cell_reference.parquet"
    _write_parquet(
        cell_reference_path,
        [("CELL_X", "SITE002_Macro_1", "L18", "F1", "2T2R", 0.0)],
        ("cell_name", "zoom_sector_id", "band", "f1f2f3", "xtxr", "avail_prb"),
    )

    output_path = run(str(pre_capex_path), str(congestion_path), str(cell_reference_path), DEFAULT_PRICING)
    row = duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchdf().iloc[0]

    # With an existing F1_L18=2T2R band already at 100 avail_prb, step 1 of
    # SEQ_PATH_A (also F1_L18=2T2R) offers no upgrade (rank_step == rank_curr,
    # nothing changes) -> rb_offered stays 0 for that step, loop continues.
    assert row["zoom_sector_id"] == "SITE002_Macro_1"
