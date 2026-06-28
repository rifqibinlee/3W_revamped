from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.dependencies import get_current_user, require_super_admin
from app.auth.models import User
from app.auth.schemas import LoginHistoryOut, LoginRequest, RegisterRequest, SetPasswordRequest, TokenPair, UserOut
from app.core.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


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


@router.get("/login-history", response_model=list[LoginHistoryOut])
def login_history(admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> list[LoginHistoryOut]:
    rows = service.list_login_history(db)
    return [
        LoginHistoryOut(id=r.id, user_id=r.user_id, username=r.user.username, ip_address=r.ip_address, logged_in_at=r.logged_in_at)
        for r in rows
    ]
