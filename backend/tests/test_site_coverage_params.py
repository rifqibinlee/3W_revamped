import duckdb

from app.ingestion.stages.site_coverage_params import run


def test_radius_from_tilt_and_femto_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.ingestion.stages.site_coverage_params.settings.parquet_dir", str(tmp_path)
    )
    monkeypatch.setattr(
        "app.ingestion.stages.site_coverage_params.settings.duckdb_path",
        str(tmp_path / "test.duckdb"),
    )

    raw = tmp_path / "site_info.csv"
    raw.write_text(
        "site_id,cell_name,azimuth,technology,antenna_height,m_tilt,e_tilt,remark\n"
        "SITE-001,SITE-001_A,120,4G,30,2,1,\n"  # trig radius: 30/tan(radians(3))
        "SITE-002,SITE-002_A,0,4G,0,0,0,FEMTO\n"  # femto override -> 50
        "SITE-003,SITE-003_A,90,2G,0,0,0,\n"  # no height/tilt -> 2G default 5000
    )

    output_path = run([str(raw)])
    rows = {
        r[1]: r[8]
        for r in duckdb.connect()
        .execute(f"SELECT * FROM read_parquet('{output_path}')")
        .fetchall()
    }

    assert rows["SITE-002_A"] == 50.0
    assert rows["SITE-003_A"] == 5000.0
    assert 500 < rows["SITE-001_A"] < 600  # ~572m for 30m height at 3 degrees
