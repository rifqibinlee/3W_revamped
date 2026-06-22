from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(minutes=30)
REFRESH_TOKEN_TTL = timedelta(days=7)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def _create_token(subject: str, role: str, ttl: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": subject, "role": role, "type": token_type, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_access_token(user_id: str, role: str) -> str:
    return _create_token(user_id, role, ACCESS_TOKEN_TTL, "access")


def create_refresh_token(user_id: str, role: str) -> str:
    return _create_token(user_id, role, REFRESH_TOKEN_TTL, "refresh")


class InvalidTokenError(Exception):
    pass


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise InvalidTokenError(f"expected a {expected_type} token, got {payload.get('type')}")
    return payload
