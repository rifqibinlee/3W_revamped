from sqlalchemy import select
from sqlalchemy.orm import Session

from app.reviews.models import Review, ReviewComment, ReviewReaction

VALID_RATINGS = range(1, 6)
VALID_REACTIONS = ("like", "dislike")


class InvalidRatingError(Exception):
    pass


class InvalidReactionError(Exception):
    pass


class NotFoundError(Exception):
    pass


def create_review(db: Session, author_id: str, category: str, rating: int, comment: str | None = None) -> Review:
    if rating not in VALID_RATINGS:
        raise InvalidRatingError(f"rating must be 1-5, got {rating}")
    review = Review(author_id=author_id, category=category, rating=rating, comment=comment)
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def get_review(db: Session, review_id: str) -> Review:
    review = db.get(Review, review_id)
    if review is None:
        raise NotFoundError(review_id)
    return review


def add_comment(db: Session, review_id: str, author_id: str, body: str) -> ReviewComment:
    comment = ReviewComment(review_id=review_id, author_id=author_id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def react(db: Session, review_id: str, user_id: str, reaction: str) -> ReviewReaction | None:
    """Toggle semantics: reacting with the same type again removes it
    (returns None); reacting with a different type switches it; reacting
    fresh creates it. Matches the legacy app's like/dislike button
    behavior (clicking an active reaction turns it off)."""
    if reaction not in VALID_REACTIONS:
        raise InvalidReactionError(f"reaction must be one of {VALID_REACTIONS}, got {reaction!r}")

    existing = db.scalar(
        select(ReviewReaction).where(ReviewReaction.review_id == review_id, ReviewReaction.user_id == user_id)
    )
    if existing is None:
        new_reaction = ReviewReaction(review_id=review_id, user_id=user_id, reaction=reaction)
        db.add(new_reaction)
        db.commit()
        db.refresh(new_reaction)
        return new_reaction

    if existing.reaction == reaction:
        db.delete(existing)
        db.commit()
        return None

    existing.reaction = reaction
    db.commit()
    db.refresh(existing)
    return existing


def reaction_counts(db: Session, review_id: str) -> dict[str, int]:
    rows = list(db.scalars(select(ReviewReaction).where(ReviewReaction.review_id == review_id)))
    return {
        "like": sum(1 for r in rows if r.reaction == "like"),
        "dislike": sum(1 for r in rows if r.reaction == "dislike"),
    }
