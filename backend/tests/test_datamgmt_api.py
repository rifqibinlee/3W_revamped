def _register_and_login(client, username, role="staff"):
    client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "password123", "role": role},
    )
    resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_staff_cannot_access_data_management(client) -> None:
    headers = _register_and_login(client, "staff_datamgmt", role="staff")
    resp = client.get("/data-management/categories", headers=headers)
    assert resp.status_code == 403


def test_admin_lists_categories(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.datamgmt.service.settings.raw_data_dir", str(tmp_path))
    headers = _register_and_login(client, "admin_datamgmt", role="admin")
    resp = client.get("/data-management/categories", headers=headers)
    assert resp.status_code == 200
    assert {c["key"] for c in resp.json()} == {"site_data", "cell_reference", "network_data"}


def test_admin_uploads_and_previews_csv(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.datamgmt.service.settings.raw_data_dir", str(tmp_path))
    headers = _register_and_login(client, "admin_datamgmt2", role="admin")

    upload_resp = client.post(
        "/data-management/categories/site_data/files",
        headers=headers,
        files={"file": ("sites.csv", b"site_id,lat,lon\nSITE001,3.1,101.6\n", "text/csv")},
    )
    assert upload_resp.status_code == 201

    list_resp = client.get("/data-management/categories/site_data/files", headers=headers)
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["filename"] == "sites.csv"

    preview_resp = client.get("/data-management/categories/site_data/files/sites.csv/preview", headers=headers)
    assert preview_resp.status_code == 200
    assert preview_resp.json()["columns"] == ["site_id", "lat", "lon"]
    assert preview_resp.json()["rows"] == [["SITE001", 3.1, 101.6]]


def test_upload_requires_valid_week_for_weekly_category(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.datamgmt.service.settings.raw_data_dir", str(tmp_path))
    headers = _register_and_login(client, "admin_datamgmt3", role="admin")

    resp = client.post(
        "/data-management/categories/network_data/files",
        headers=headers,
        files={"file": ("prb.csv", b"x\n1\n", "text/csv")},
    )
    assert resp.status_code == 400


def test_run_pipeline_sync_with_no_files_skips_everything(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.datamgmt.service.settings.raw_data_dir", str(tmp_path))
    headers = _register_and_login(client, "admin_datamgmt4", role="admin")

    resp = client.post("/data-management/run-pipeline?sync=true", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["stages_run"] == []


def test_delete_file_via_api(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.datamgmt.service.settings.raw_data_dir", str(tmp_path))
    headers = _register_and_login(client, "admin_datamgmt5", role="admin")

    client.post(
        "/data-management/categories/site_data/files",
        headers=headers,
        files={"file": ("sites.csv", b"a,b\n1,2\n", "text/csv")},
    )
    del_resp = client.delete("/data-management/categories/site_data/files/sites.csv", headers=headers)
    assert del_resp.status_code == 204

    list_resp = client.get("/data-management/categories/site_data/files", headers=headers)
    assert list_resp.json() == []
