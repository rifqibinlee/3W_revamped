from app.auth import service
from app.auth.models import Role
from app.auth.security import create_access_token, decode_token


def test_register_and_authenticate(db_session) -> None:
    user = service.register_user(db_session, "alice", "alice@example.com", "supersecret", Role.PLANNER)
    assert user.role == Role.PLANNER

    authed = service.authenticate(db_session, "alice", "supersecret")
    assert authed.id == user.id
    assert len(authed.login_history) == 1


def test_authenticate_wrong_password_raises(db_session) -> None:
    service.register_user(db_session, "bob", "bob@example.com", "correctpassword", Role.STAFF)
    try:
        service.authenticate(db_session, "bob", "wrongpassword")
        assert False, "expected InvalidCredentialsError"
    except service.InvalidCredentialsError:
        pass


def test_duplicate_username_rejected(db_session) -> None:
    service.register_user(db_session, "carol", "carol@example.com", "password1", Role.STAFF)
    try:
        service.register_user(db_session, "carol", "other@example.com", "password2", Role.STAFF)
        assert False, "expected UsernameTakenError"
    except service.UsernameTakenError:
        pass


def test_token_roundtrip() -> None:
    token = create_access_token("user-123", "admin")
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "user-123"
    assert payload["role"] == "admin"


def test_register_login_me_via_api(client) -> None:
    register_resp = client.post(
        "/auth/register",
        json={"username": "dave", "email": "dave@example.com", "password": "password123", "role": "staff"},
    )
    assert register_resp.status_code == 201

    login_resp = client.post("/auth/login", json={"username": "dave", "password": "password123"})
    assert login_resp.status_code == 200
    access_token = login_resp.json()["access_token"]

    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "dave"


def test_login_wrong_password_via_api_returns_401(client) -> None:
    client.post(
        "/auth/register",
        json={"username": "erin", "email": "erin@example.com", "password": "password123", "role": "staff"},
    )
    resp = client.post("/auth/login", json={"username": "erin", "password": "wrong"})
    assert resp.status_code == 401


def test_me_without_token_returns_401(client) -> None:
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_list_users_requires_auth(client) -> None:
    resp = client.get("/auth/users")
    assert resp.status_code == 401


def test_list_users_returns_directory(client) -> None:
    client.post(
        "/auth/register",
        json={"username": "frank", "email": "frank@example.com", "password": "password123", "role": "staff"},
    )
    client.post(
        "/auth/register",
        json={"username": "grace", "email": "grace@example.com", "password": "password123", "role": "planner"},
    )
    login_resp = client.post("/auth/login", json={"username": "frank", "password": "password123"})
    headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

    resp = client.get("/auth/users", headers=headers)
    assert resp.status_code == 200
    usernames = {u["username"] for u in resp.json()}
    assert {"frank", "grace"}.issubset(usernames)


def test_set_password_changes_authentication(db_session) -> None:
    user = service.register_user(db_session, "erin", "erin@example.com", "oldpassword", Role.STAFF)
    service.set_password(db_session, user, "newpassword123")
    try:
        service.authenticate(db_session, "erin", "oldpassword")
        assert False, "expected InvalidCredentialsError"
    except service.InvalidCredentialsError:
        pass
    authed = service.authenticate(db_session, "erin", "newpassword123")
    assert authed.id == user.id


def test_delete_user_without_activity_succeeds(db_session) -> None:
    user = service.register_user(db_session, "frank", "frank@example.com", "password123", Role.STAFF)
    service.delete_user(db_session, user)
    try:
        service.get_user(db_session, user.id)
        assert False, "expected UserNotFoundError"
    except service.UserNotFoundError:
        pass


def test_delete_user_with_activity_raises(db_session, monkeypatch) -> None:
    """The test DB is in-memory SQLite without FK enforcement turned on,
    so a real orphaning delete wouldn't actually raise there the way it
    would against real Postgres — simulate the IntegrityError commit
    would surface instead of relying on FK enforcement we don't control
    in this test environment."""
    from sqlalchemy.exc import IntegrityError

    user = service.register_user(db_session, "grace", "grace@example.com", "password123", Role.STAFF)

    def raise_integrity_error():
        raise IntegrityError("statement", {}, Exception("FK violation"))

    monkeypatch.setattr(db_session, "commit", raise_integrity_error)
    try:
        service.delete_user(db_session, user)
        assert False, "expected UserHasActivityError"
    except service.UserHasActivityError:
        pass


def test_super_admin_bypasses_require_roles() -> None:
    from app.auth.dependencies import require_roles
    from app.auth.models import Role as RoleEnum, User

    super_admin = User(username="root", email="root@example.com", password_hash="x", role=RoleEnum.SUPER_ADMIN)
    check = require_roles(RoleEnum.PLANNER)
    result = check(user=super_admin)
    assert result is super_admin


def _register_and_login_super_admin(client, username):
    client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "password123", "role": "super_admin"},
    )
    resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _register_and_login(client, username):
    client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "password123", "role": "staff"},
    )
    resp = client.post("/auth/login", json={"username": username, "password": "password123"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_non_super_admin_cannot_set_password_via_api(client) -> None:
    target_headers = _register_and_login(client, "target_user")
    target_id = client.get("/auth/me", headers=target_headers).json()["id"]
    other_headers = _register_and_login(client, "other_user")

    resp = client.put(f"/auth/users/{target_id}/password", json={"new_password": "brandnewpass"}, headers=other_headers)
    assert resp.status_code == 403


def test_super_admin_can_set_password_via_api(client) -> None:
    target_headers = _register_and_login(client, "target_user2")
    target_id = client.get("/auth/me", headers=target_headers).json()["id"]
    admin_headers = _register_and_login_super_admin(client, "super_setpw")

    resp = client.put(f"/auth/users/{target_id}/password", json={"new_password": "brandnewpass"}, headers=admin_headers)
    assert resp.status_code == 204

    login_resp = client.post("/auth/login", json={"username": "target_user2", "password": "brandnewpass"})
    assert login_resp.status_code == 200


def test_non_super_admin_cannot_view_login_history(client) -> None:
    headers = _register_and_login(client, "viewer_user")
    resp = client.get("/auth/login-history", headers=headers)
    assert resp.status_code == 403


def test_super_admin_can_view_login_history(client) -> None:
    _register_and_login(client, "history_user")
    admin_headers = _register_and_login_super_admin(client, "super_history")

    resp = client.get("/auth/login-history", headers=admin_headers)
    assert resp.status_code == 200
    usernames = {row["username"] for row in resp.json()}
    assert "history_user" in usernames
    assert "super_history" in usernames


def test_super_admin_can_delete_user_via_api(client) -> None:
    target_headers = _register_and_login(client, "deletable_user")
    target_id = client.get("/auth/me", headers=target_headers).json()["id"]
    admin_headers = _register_and_login_super_admin(client, "super_deluser")

    resp = client.delete(f"/auth/users/{target_id}", headers=admin_headers)
    assert resp.status_code == 204

    login_resp = client.post("/auth/login", json={"username": "deletable_user", "password": "password123"})
    assert login_resp.status_code == 401


def test_change_own_password_requires_current_password(db_session) -> None:
    user = service.register_user(db_session, "harriet", "harriet@example.com", "oldpassword", Role.STAFF)
    try:
        service.change_own_password(db_session, user, "wrongcurrent", "newpassword123")
        assert False, "expected WrongPasswordError"
    except service.WrongPasswordError:
        pass
    # password unchanged
    authed = service.authenticate(db_session, "harriet", "oldpassword")
    assert authed.id == user.id


def test_change_own_password_succeeds_with_correct_current(db_session) -> None:
    user = service.register_user(db_session, "ivan", "ivan@example.com", "oldpassword", Role.STAFF)
    service.change_own_password(db_session, user, "oldpassword", "newpassword123")
    authed = service.authenticate(db_session, "ivan", "newpassword123")
    assert authed.id == user.id


def test_set_avatar_url_persists(db_session) -> None:
    user = service.register_user(db_session, "judy", "judy@example.com", "password123", Role.STAFF)
    updated = service.set_avatar_url(db_session, user, "/avatars/judy-123.png")
    assert updated.avatar_url == "/avatars/judy-123.png"


def test_change_own_password_via_api(client) -> None:
    headers = _register_and_login(client, "kyle_pw")
    resp = client.put(
        "/auth/me/password",
        json={"current_password": "password123", "new_password": "freshpassword456"},
        headers=headers,
    )
    assert resp.status_code == 204
    login_resp = client.post("/auth/login", json={"username": "kyle_pw", "password": "freshpassword456"})
    assert login_resp.status_code == 200


def test_change_own_password_via_api_rejects_wrong_current(client) -> None:
    headers = _register_and_login(client, "liam_pw")
    resp = client.put(
        "/auth/me/password",
        json={"current_password": "notright", "new_password": "freshpassword456"},
        headers=headers,
    )
    assert resp.status_code == 401


def test_upload_avatar_via_api(client, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("app.auth.router.settings.avatar_dir", str(tmp_path))
    headers = _register_and_login(client, "mona_avatar")

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32  # not a real PNG, just bytes — content-type is what's checked
    resp = client.post(
        "/auth/me/avatar",
        files={"file": ("avatar.png", png_bytes, "image/png")},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["avatar_url"].startswith("/avatars/")
    assert body["avatar_url"].endswith(".png")


def test_upload_avatar_rejects_non_image(client) -> None:
    headers = _register_and_login(client, "nina_avatar")
    resp = client.post(
        "/auth/me/avatar",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 400
