from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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


class UserNotFoundError(Exception):
    pass


def get_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(user_id)
    return user


def set_password(db: Session, user: User, new_password: str) -> None:
    """Super-Admin-initiated password reset — no current-password check,
    unlike a self-service change, since the admin isn't the account
    holder."""
    user.password_hash = hash_password(new_password)
    db.commit()


class UserHasActivityError(Exception):
    """Raised instead of cascading the delete through every table that
    references this user (projects, annotations, tasks, messages,
    comments, login history...) — silently destroying a user's entire
    history just because an admin removed their account would be far
    more surprising than just refusing the delete."""

    pass


def delete_user(db: Session, user: User) -> None:
    db.query(LoginHistory).filter(LoginHistory.user_id == user.id).delete()
    db.flush()
    try:
        db.delete(user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise UserHasActivityError(user.id) from None


def list_login_history(db: Session) -> list[LoginHistory]:
    return list(db.scalars(select(LoginHistory).order_by(LoginHistory.logged_in_at.desc())))
