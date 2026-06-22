def _register_and_login(client, username):
    client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "password123", "role": "staff"},
    )
    resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_note_via_api(client) -> None:
    headers = _register_and_login(client, "alice_api")
    resp = client.post(
        "/annotations",
        json={"title": "Pole down", "geometry": {"type": "Point", "coordinates": [101.5, 3.1]}},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] is None
    assert body["assignee_id"] is None


def test_full_task_lifecycle_via_api(client) -> None:
    creator_headers = _register_and_login(client, "creator_api")
    assignee_headers = _register_and_login(client, "assignee_api")

    # Look up assignee's id via /auth/me
    assignee_id = client.get("/auth/me", headers=assignee_headers).json()["id"]

    create_resp = client.post(
        "/annotations",
        json={
            "title": "Fix antenna",
            "geometry": {"type": "Point", "coordinates": [101.5, 3.1]},
            "assignee_id": assignee_id,
            "due_date": "2026-12-31T00:00:00Z",
        },
        headers=creator_headers,
    )
    assert create_resp.status_code == 201
    annotation_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "todo"

    start_resp = client.post(f"/annotations/{annotation_id}/start", headers=assignee_headers)
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "in_progress"

    submit_resp = client.post(f"/annotations/{annotation_id}/submit", headers=assignee_headers)
    assert submit_resp.status_code == 200
    assert submit_resp.json()["status"] == "pending_review"

    # Assignee can't approve their own task
    self_approve_resp = client.post(f"/annotations/{annotation_id}/approve", headers=assignee_headers)
    assert self_approve_resp.status_code == 403

    approve_resp = client.post(f"/annotations/{annotation_id}/approve", headers=creator_headers)
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "done"


def test_gantt_endpoint_excludes_notes(client) -> None:
    creator_headers = _register_and_login(client, "creator_gantt")
    assignee_headers = _register_and_login(client, "assignee_gantt")
    assignee_id = client.get("/auth/me", headers=assignee_headers).json()["id"]

    client.post(
        "/annotations",
        json={"title": "Just a note", "geometry": {"type": "Point", "coordinates": [0, 0]}},
        headers=creator_headers,
    )
    client.post(
        "/annotations",
        json={
            "title": "Real task",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "assignee_id": assignee_id,
            "due_date": "2026-12-31T00:00:00Z",
        },
        headers=creator_headers,
    )

    resp = client.get("/annotations/gantt/rows")
    assert resp.status_code == 200
    titles = [row["title"] for row in resp.json()]
    assert titles == ["Real task"]
