def _register_and_login(client, username):
    client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "password123", "role": "staff"},
    )
    resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_direct_conversation_and_messaging_via_api(client) -> None:
    alice_headers = _register_and_login(client, "alice_chat_api")
    bob_headers = _register_and_login(client, "bob_chat_api")
    bob_id = client.get("/auth/me", headers=bob_headers).json()["id"]

    conv_resp = client.post("/chat/conversations/direct", json={"other_user_id": bob_id}, headers=alice_headers)
    assert conv_resp.status_code == 201
    conv_id = conv_resp.json()["id"]

    msg_resp = client.post(f"/chat/conversations/{conv_id}/messages", json={"body": "hello bob"}, headers=alice_headers)
    assert msg_resp.status_code == 201

    list_resp = client.get(f"/chat/conversations/{conv_id}/messages", headers=bob_headers)
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["body"] == "hello bob"


def test_non_participant_blocked_via_api(client) -> None:
    alice_headers = _register_and_login(client, "alice2_chat_api")
    bob_headers = _register_and_login(client, "bob2_chat_api")
    eve_headers = _register_and_login(client, "eve2_chat_api")
    bob_id = client.get("/auth/me", headers=bob_headers).json()["id"]

    conv_resp = client.post("/chat/conversations/direct", json={"other_user_id": bob_id}, headers=alice_headers)
    conv_id = conv_resp.json()["id"]

    resp = client.get(f"/chat/conversations/{conv_id}/messages", headers=eve_headers)
    assert resp.status_code == 403
