def _register_and_login(client, username, role="staff"):
    client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "password123", "role": role},
    )
    resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_staff_cannot_update_pricing(client) -> None:
    headers = _register_and_login(client, "staff_pricing", role="staff")
    resp = client.put("/capex-pricing/EQ/BW Upg", json={"price": 1.0}, headers=headers)
    assert resp.status_code == 403


def test_admin_can_update_pricing(client) -> None:
    headers = _register_and_login(client, "admin_pricing", role="admin")
    resp = client.put("/capex-pricing/EQ/BW Upg", json={"price": 7777.0}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["EQ"]["BW Upg"] == 7777.0


def test_anyone_can_read_pricing(client) -> None:
    resp = client.get("/capex-pricing")
    assert resp.status_code == 200
