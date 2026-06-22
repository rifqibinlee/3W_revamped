import duckdb

from app.ingestion.stages.site_coordinates import run


def test_dedupes_and_drops_missing_coords(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.ingestion.stages.site_coordinates.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.ingestion.stages.site_coordinates.settings.duckdb_path", str(tmp_path / "test.duckdb")
    )

    raw = tmp_path / "raw_sites.csv"
    raw.write_text(
        "site_id,region,cluster,latitude,longitude\n"
        "SITE-001,Central,A,3.1,101.6\n"
        "SITE_001,Central,A,3.15,101.65\n"  # duplicate after normalization, last wins
        "SITE-002,,B,,\n"  # missing coords, dropped
    )

    output_path = run([str(raw)])
    result = duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchall()

    assert len(result) == 1
    assert result[0][0] == "site001"
