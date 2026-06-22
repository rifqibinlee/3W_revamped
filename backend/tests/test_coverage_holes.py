import duckdb

from app.ingestion.stages.coverage_holes import run


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingestion.stages.coverage_holes.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.ingestion.stages.coverage_holes.settings.duckdb_path", str(tmp_path / "test.duckdb")
    )


def _read_output(output_path):
    cols = [d[0] for d in duckdb.connect().execute(f"DESCRIBE SELECT * FROM read_parquet('{output_path}')").fetchall()]
    return [dict(zip(cols, r)) for r in duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchall()]


def test_signal_threshold_filter_and_clustering(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    raw = tmp_path / "mr_data.csv"
    raw.write_text(
        "Serving Cell,Latitude,Longitude,Signal\n"
        # Tight cluster of 4 points within ~50m (default eps threshold for <=10 points)
        "CELL_A,3.00000,101.00000,-115\n"
        "CELL_A,3.00005,101.00005,-115\n"
        "CELL_A,3.00010,101.00010,-115\n"
        "CELL_A,3.00015,101.00015,-115\n"
        # Isolated point ~150km away -> noise
        "CELL_B,4.00000,102.00000,-115\n"
        # Good signal, above -110 threshold -> excluded entirely
        "CELL_C,3.00000,101.00000,-90\n"
    )

    output_path = run([str(raw)])
    rows = _read_output(output_path)

    assert len(rows) == 5  # the -90 row is dropped
    cluster_points = [r for r in rows if r["serving_cell"] == "CELL_A"]
    noise_point = next(r for r in rows if r["serving_cell"] == "CELL_B")

    cluster_ids = {r["cluster_id"] for r in cluster_points}
    assert len(cluster_ids) == 1
    assert next(iter(cluster_ids)) != -1
    assert noise_point["cluster_id"] == -1
    assert all(r["data_source"] == "MR" for r in rows)


def test_ookla_signature_columns_detected(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    raw = tmp_path / "ookla_data.csv"
    raw.write_text(
        "Cell_ID,Latitude,Longitude,Signal\n"
        "CELL_X,3.0,101.0,-120\n"
        "CELL_X,3.0001,101.0001,-120\n"
        "CELL_X,3.0002,101.0002,-120\n"
    )

    output_path = run([str(raw)])
    rows = _read_output(output_path)

    assert len(rows) == 3
    assert all(r["data_source"] == "Ookla" for r in rows)


def test_no_qualifying_columns_returns_none(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    raw = tmp_path / "irrelevant.csv"
    raw.write_text("foo,bar\n1,2\n")

    output_path = run([str(raw)])
    assert output_path is None
