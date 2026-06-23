from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import LoginHistory, Role, User
from app.auth.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)


class UsernameTakenError(Exception):
    pass


class EmailTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


def register_user(db: Session, username: str, email: str, password: str, role: Role) -> User:
    if db.scalar(select(User).where(User.username == username)):
        raise UsernameTakenError(username)
    if db.scalar(select(User).where(User.email == email)):
        raise EmailTakenError(email)

    user = User(username=username, email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, username: str, password: str, ip_address: str | None = None) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError(username)

    db.add(LoginHistory(user_id=user.id, ip_address=ip_address))
    db.commit()
    return user


def issue_tokens(user: User) -> tuple[str, str]:
    return create_access_token(user.id, user.role), create_refresh_token(user.id, user.role)


def list_users(db: Session) -> list[User]:
    """Lets the frontend populate an assignee picker — any authenticated
    user can see the directory, there's nothing sensitive in id/username/
    role beyond what /auth/me already exposes about yourself."""
    return list(db.scalars(select(User).order_by(User.username)))
