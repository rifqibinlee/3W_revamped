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
    resp = client.put(
        "/capex-pricing/EQ/BW Upg",
        json={"price": 7777.0, "price_min": 7000.0, "price_max": 8500.0},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["EQ"]["BW Upg"] == {"price": 7777.0, "price_min": 7000.0, "price_max": 8500.0}


def test_unauthenticated_cannot_read_pricing(client) -> None:
    resp = client.get("/capex-pricing")
    assert resp.status_code == 401


def test_admin_sees_exact_price(client) -> None:
    headers = _register_and_login(client, "admin_pricing_read", role="admin")
    client.put(
        "/capex-pricing/EQ/BW Upg",
        json={"price": 5000.0, "price_min": 4000.0, "price_max": 6000.0},
        headers=headers,
    )
    resp = client.get("/capex-pricing", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["EQ"]["BW Upg"] == {"price": 5000.0, "price_min": 4000.0, "price_max": 6000.0}


def test_staff_only_sees_price_range(client) -> None:
    admin_headers = _register_and_login(client, "admin_pricing_staffview", role="admin")
    client.put(
        "/capex-pricing/EQ/BW Upg",
        json={"price": 5000.0, "price_min": 4000.0, "price_max": 6000.0},
        headers=admin_headers,
    )
    staff_headers = _register_and_login(client, "staff_pricing_read", role="staff")
    resp = client.get("/capex-pricing", headers=staff_headers)
    assert resp.status_code == 200
    assert resp.json()["EQ"]["BW Upg"] == {"price_min": 4000.0, "price_max": 6000.0}
