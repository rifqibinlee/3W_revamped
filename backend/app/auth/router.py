from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.auth.schemas import LoginRequest, RegisterRequest, TokenPair, UserOut
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
