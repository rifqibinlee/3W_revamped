from app.datamgmt import service


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.datamgmt.service.settings.raw_data_dir", str(tmp_path))


def test_list_categories_empty(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    categories = service.list_categories()
    assert {c["key"] for c in categories} == {"site_data", "cell_reference", "network_data"}
    assert all(c["file_count"] == 0 for c in categories)


def test_unknown_category_rejected(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    try:
        service.list_files("bogus")
        assert False, "expected UnknownCategoryError"
    except service.UnknownCategoryError:
        pass


def test_non_weekly_category_ignores_week(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    service.save_file("site_data", None, "sites.csv", b"site_id,lat,lon\nA,1,2\n")
    assert [f["filename"] for f in service.list_files("site_data")] == ["sites.csv"]


def test_weekly_category_requires_valid_week(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    try:
        service.save_file("network_data", None, "prb.csv", b"x\n1\n")
        assert False, "expected InvalidWeekError"
    except service.InvalidWeekError:
        pass

    try:
        service.save_file("network_data", "not-a-week", "prb.csv", b"x\n1\n")
        assert False, "expected InvalidWeekError"
    except service.InvalidWeekError:
        pass


def test_weekly_category_save_and_list(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    service.save_file("network_data", "2026-W13", "prb.csv", b"x\n1\n")
    service.save_file("network_data", "2026-W14", "prb.csv", b"x\n1\n")

    assert service.list_weeks("network_data") == ["2026-W14", "2026-W13"]
    assert [f["filename"] for f in service.list_files("network_data", "2026-W13")] == ["prb.csv"]

    categories = service.list_categories()
    network = next(c for c in categories if c["key"] == "network_data")
    assert network["file_count"] == 2


def test_unsupported_file_type_rejected(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    try:
        service.save_file("site_data", None, "notes.txt", b"hello")
        assert False, "expected UnsupportedFileTypeError"
    except service.UnsupportedFileTypeError:
        pass


def test_delete_file(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    service.save_file("site_data", None, "sites.csv", b"a,b\n1,2\n")
    service.delete_file("site_data", None, "sites.csv")
    assert service.list_files("site_data") == []


def test_save_file_strips_path_traversal(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    service.save_file("site_data", None, "../../evil.csv", b"a,b\n1,2\n")
    files = service.list_files("site_data")
    assert files[0]["filename"] == "evil.csv"


def test_preview_csv_file(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    service.save_file("site_data", None, "sites.csv", b"site_id,lat,lon\nSITE001,3.1,101.6\nSITE002,3.2,101.7\n")

    preview = service.preview_file("site_data", None, "sites.csv")
    assert preview["columns"] == ["site_id", "lat", "lon"]
    assert preview["rows"] == [["SITE001", 3.1, 101.6], ["SITE002", 3.2, 101.7]]
    assert preview["truncated"] is False


def test_preview_missing_file_raises(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    try:
        service.preview_file("site_data", None, "missing.csv")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_run_pipeline_skips_everything_when_no_files(tmp_path, monkeypatch) -> None:
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("app.ingestion.stages.site_coordinates.settings.parquet_dir", str(tmp_path / "parquet"))
    result = service.run_pipeline()
    assert result["stages_run"] == []
    assert any("cell_reference" in s for s in result["stages_skipped"])
