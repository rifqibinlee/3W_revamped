from datetime import datetime

from pydantic import BaseModel


class ReviewCreate(BaseModel):
    category: str
    rating: int
    comment: str | None = None


class CommentCreate(BaseModel):
    body: str


class ReactionRequest(BaseModel):
    reaction: str


class ReviewOut(BaseModel):
    id: str
    author_id: str
    category: str
    rating: int
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CommentOut(BaseModel):
    id: str
    review_id: str
    author_id: str
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}
