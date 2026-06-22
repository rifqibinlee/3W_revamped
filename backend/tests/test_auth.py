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
