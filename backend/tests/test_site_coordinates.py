import duckdb

from app.ingestion.stages.site_coordinates import run


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ingestion.stages.site_coordinates.settings.parquet_dir", str(tmp_path))
    monkeypatch.setattr(
        "app.ingestion.stages.site_coordinates.settings.duckdb_path", str(tmp_path / "test.duckdb")
    )


def test_dedupes_and_drops_missing_coords(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    raw = tmp_path / "raw_sites.csv"
    raw.write_text(
        "site_id,region,cluster,latitude,longitude\n"
        "SITE-001,Central,A,3.1,101.6\n"
        # Legacy clean_site_id splits on the first delimiter and keeps only
        # the prefix, so "SITE-001" and "SITE_001" both collapse to "SITE" —
        # this matches the real legacy script (it was designed for
        # cell-name-style values with a trailing sector suffix), not an
        # invented normalization.
        "SITE_001,Central,A,3.15,101.65\n"  # duplicate after normalization, last wins
        "SITE-002,,B,,\n"  # missing coords, dropped
    )

    output_path = run([str(raw)])
    result = duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchall()

    assert len(result) == 1
    assert result[0][0] == "SITE"


def test_detects_columns_by_keyword_when_names_differ(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    raw = tmp_path / "raw_sites.csv"
    raw.write_text(
        "Site Id,Lat,Long,Region\n"
        "ALPHA001,3.5,101.7,North\n"
    )

    output_path = run([str(raw)])
    result = duckdb.connect().execute(f"SELECT * FROM read_parquet('{output_path}')").fetchall()

    assert len(result) == 1
    assert result[0][0] == "ALPHA001"
    assert result[0][1] == "North"
