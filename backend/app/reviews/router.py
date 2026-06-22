from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.db import get_db
from app.reviews import service
from app.reviews.models import Review, ReviewComment
from app.reviews.schemas import CommentCreate, CommentOut, ReactionRequest, ReviewCreate, ReviewOut

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def create(payload: ReviewCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Review:
    try:
        return service.create_review(db, user.id, payload.category, payload.rating, payload.comment)
    except service.InvalidRatingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/{review_id}", response_model=ReviewOut)
def get(review_id: str, db: Session = Depends(get_db)) -> Review:
    try:
        return service.get_review(db, review_id)
    except service.NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found") from exc


@router.post("/{review_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(review_id: str, payload: CommentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ReviewComment:
    return service.add_comment(db, review_id, user.id, payload.body)


@router.post("/{review_id}/react")
def react(review_id: str, payload: ReactionRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    try:
        service.react(db, review_id, user.id, payload.reaction)
    except service.InvalidReactionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return service.reaction_counts(db, review_id)


@router.get("/{review_id}/reactions")
def reactions(review_id: str, db: Session = Depends(get_db)) -> dict:
    return service.reaction_counts(db, review_id)
