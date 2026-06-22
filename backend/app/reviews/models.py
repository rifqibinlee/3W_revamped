import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Review(Base):
    """General feedback/reviews — distinct from the per-task review
    workflow in app.annotations (that's an approval gate on a task;
    this is open-ended user feedback with a rating, like the legacy
    app's reviews/feedback module)."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    category: Mapped[str] = mapped_column(String(50))
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReviewComment(Base):
    __tablename__ = "review_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReviewReaction(Base):
    __tablename__ = "review_reactions"
    __table_args__ = (UniqueConstraint("review_id", "user_id", name="uq_review_reaction_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reaction: Mapped[str] = mapped_column(String(10))  # "like" or "dislike"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
