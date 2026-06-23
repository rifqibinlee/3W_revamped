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
    resp = client.post("/projects", json={"title": "Pole down"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["assignee_id"] is None
    assert body["conversation_id"] is None


def test_list_projects_via_api(client) -> None:
    headers = _register_and_login(client, "alice_list_api")
    client.post("/projects", json={"title": "Note one"}, headers=headers)
    client.post("/projects", json={"title": "Note two"}, headers=headers)

    resp = client.get("/projects")
    assert resp.status_code == 200
    titles = {p["title"] for p in resp.json()}
    assert {"Note one", "Note two"}.issubset(titles)


def test_add_annotation_to_project_via_api(client) -> None:
    headers = _register_and_login(client, "alice_api2")
    project_id = client.post("/projects", json={"title": "Survey area"}, headers=headers).json()["id"]

    resp = client.post(
        f"/projects/{project_id}/annotations",
        json={"geometry": {"type": "Point", "coordinates": [101.5, 3.1]}, "label": "pole 1"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["project_id"] == project_id

    list_resp = client.get(f"/projects/{project_id}/annotations")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


def test_cannot_create_task_under_note_via_api(client) -> None:
    headers = _register_and_login(client, "alice_api3")
    project_id = client.post("/projects", json={"title": "Just a note"}, headers=headers).json()["id"]
    me_id = client.get("/auth/me", headers=headers).json()["id"]

    resp = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Do something", "assignee_ids": [me_id], "due_date": "2026-12-31T00:00:00Z"},
        headers=headers,
    )
    assert resp.status_code == 409


def test_full_task_lifecycle_via_api(client) -> None:
    creator_headers = _register_and_login(client, "creator_api")
    assignee_headers = _register_and_login(client, "assignee_api")
    assignee_id = client.get("/auth/me", headers=assignee_headers).json()["id"]

    project_id = client.post(
        "/projects", json={"title": "Fix antenna", "assignee_id": assignee_id}, headers=creator_headers
    ).json()["id"]

    create_resp = client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Climb tower", "assignee_ids": [assignee_id], "due_date": "2026-12-31T00:00:00Z"},
        headers=creator_headers,
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "todo"
    assert create_resp.json()["assignee_ids"] == [assignee_id]

    start_resp = client.post(f"/tasks/{task_id}/start", headers=assignee_headers)
    assert start_resp.status_code == 200
    assert start_resp.json()["status"] == "in_progress"

    submit_resp = client.post(f"/tasks/{task_id}/submit", headers=assignee_headers)
    assert submit_resp.status_code == 200
    assert submit_resp.json()["status"] == "pending_review"

    self_approve_resp = client.post(f"/tasks/{task_id}/approve", headers=assignee_headers)
    assert self_approve_resp.status_code == 403

    approve_resp = client.post(f"/tasks/{task_id}/approve", headers=creator_headers)
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "done"


def test_gantt_endpoint_lists_tasks(client) -> None:
    creator_headers = _register_and_login(client, "creator_gantt")
    assignee_headers = _register_and_login(client, "assignee_gantt")
    assignee_id = client.get("/auth/me", headers=assignee_headers).json()["id"]

    client.post("/projects", json={"title": "Just a note"}, headers=creator_headers)
    project_id = client.post(
        "/projects", json={"title": "Real project", "assignee_id": assignee_id}, headers=creator_headers
    ).json()["id"]
    client.post(
        f"/projects/{project_id}/tasks",
        json={"title": "Real task", "assignee_ids": [assignee_id], "due_date": "2026-12-31T00:00:00Z"},
        headers=creator_headers,
    )

    resp = client.get("/tasks/gantt/rows")
    assert resp.status_code == 200
    titles = [row["title"] for row in resp.json()]
    assert titles == ["Real task"]


def test_comments_listed_in_order_via_api(client) -> None:
    headers = _register_and_login(client, "alice_comments_api")
    project_id = client.post("/projects", json={"title": "Note with comments"}, headers=headers).json()["id"]

    client.post(f"/projects/{project_id}/comments", json={"body": "first"}, headers=headers)
    client.post(f"/projects/{project_id}/comments", json={"body": "second"}, headers=headers)

    resp = client.get(f"/projects/{project_id}/comments")
    assert resp.status_code == 200
    assert [c["body"] for c in resp.json()] == ["first", "second"]
