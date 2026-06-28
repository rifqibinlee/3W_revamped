from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.auth.models import Role


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8)
    role: Role = Role.STAFF


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    role: Role
    created_at: datetime

    model_config = {"from_attributes": True}


class SetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8)


class LoginHistoryOut(BaseModel):
    id: str
    user_id: str
    username: str
    ip_address: str | None
    logged_in_at: datetime

    model_config = {"from_attributes": True}
