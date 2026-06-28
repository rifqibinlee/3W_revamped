import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.dependencies import get_current_user, require_super_admin
from app.auth.models import User
from app.auth.schemas import (
    ChangePasswordRequest,
    LoginHistoryOut,
    LoginRequest,
    RegisterRequest,
    SetPasswordRequest,
    TokenPair,
    UserOut,
)
from app.core.config import settings
from app.core.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

_ALLOWED_AVATAR_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_MAX_AVATAR_BYTES = 5 * 1024 * 1024


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    try:
        return service.register_user(db, payload.username, payload.email, payload.password, payload.role)
    except service.UsernameTakenError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken") from exc
    except service.EmailTakenError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from exc


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    try:
        user = service.authenticate(db, payload.username, payload.password, request.client.host if request.client else None)
    except service.InvalidCredentialsError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password") from exc

    access_token, refresh_token = service.issue_tokens(user)
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[User]:
    return service.list_users(db)


@router.put("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def set_password(
    user_id: str, payload: SetPasswordRequest,
    admin: User = Depends(require_super_admin), db: Session = Depends(get_db),
) -> None:
    try:
        target = service.get_user(db, user_id)
    except service.UserNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found") from exc
    service.set_password(db, target, payload.new_password)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: str, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> None:
    try:
        target = service.get_user(db, user_id)
    except service.UserNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found") from exc
    try:
        service.delete_user(db, target)
    except service.UserHasActivityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This user has projects, annotations, messages, or comments — remove those first",
        ) from exc


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_own_password(
    payload: ChangePasswordRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> None:
    try:
        service.change_own_password(db, user, payload.current_password, payload.new_password)
    except service.WrongPasswordError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is incorrect") from exc


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile, user: User = Depends(get_current_user), db: Session = Depends(get_db),
) -> User:
    ext = _ALLOWED_AVATAR_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Avatar must be a PNG, JPEG, or WebP image")

    content = await file.read()
    if len(content) > _MAX_AVATAR_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Avatar must be 5MB or smaller")

    avatar_dir = Path(settings.avatar_dir)
    avatar_dir.mkdir(parents=True, exist_ok=True)
    # A fresh filename per upload, not a name keyed on the user id —
    # browsers/CDNs cache aggressively by URL, so reusing the same
    # filename on every re-upload would mean the old picture keeps
    # showing until a hard refresh.
    filename = f"{user.id}-{uuid.uuid4().hex[:8]}{ext}"
    (avatar_dir / filename).write_bytes(content)

    return service.set_avatar_url(db, user, f"/avatars/{filename}")


@router.get("/login-history", response_model=list[LoginHistoryOut])
def login_history(admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> list[LoginHistoryOut]:
    rows = service.list_login_history(db)
    return [
        LoginHistoryOut(id=r.id, user_id=r.user_id, username=r.user.username, ip_address=r.ip_address, logged_in_at=r.logged_in_at)
        for r in rows
    ]
