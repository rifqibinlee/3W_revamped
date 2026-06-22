from app.auth import service as auth_service
from app.auth.models import Role
from app.reviews import service


def _user(db_session, username: str):
    return auth_service.register_user(db_session, username, f"{username}@example.com", "password123", Role.STAFF)


def test_create_review(db_session) -> None:
    author = _user(db_session, "author_review")
    review = service.create_review(db_session, author.id, "ui", 4, "pretty good")
    assert review.rating == 4
    assert review.category == "ui"


def test_invalid_rating_rejected(db_session) -> None:
    author = _user(db_session, "author_review2")
    try:
        service.create_review(db_session, author.id, "ui", 6)
        assert False, "expected InvalidRatingError"
    except service.InvalidRatingError:
        pass


def test_add_comment(db_session) -> None:
    author = _user(db_session, "author_review3")
    review = service.create_review(db_session, author.id, "ui", 5)
    comment = service.add_comment(db_session, review.id, author.id, "thanks!")
    assert comment.body == "thanks!"


def test_react_creates_then_toggles_off(db_session) -> None:
    author = _user(db_session, "author_review4")
    reactor = _user(db_session, "reactor_review4")
    review = service.create_review(db_session, author.id, "ui", 5)

    reaction = service.react(db_session, review.id, reactor.id, "like")
    assert reaction.reaction == "like"
    assert service.reaction_counts(db_session, review.id) == {"like": 1, "dislike": 0}

    # Same reaction again -> toggled off
    result = service.react(db_session, review.id, reactor.id, "like")
    assert result is None
    assert service.reaction_counts(db_session, review.id) == {"like": 0, "dislike": 0}


def test_react_switches_type(db_session) -> None:
    author = _user(db_session, "author_review5")
    reactor = _user(db_session, "reactor_review5")
    review = service.create_review(db_session, author.id, "ui", 5)

    service.react(db_session, review.id, reactor.id, "like")
    result = service.react(db_session, review.id, reactor.id, "dislike")
    assert result.reaction == "dislike"
    assert service.reaction_counts(db_session, review.id) == {"like": 0, "dislike": 1}


def test_invalid_reaction_rejected(db_session) -> None:
    author = _user(db_session, "author_review6")
    review = service.create_review(db_session, author.id, "ui", 5)
    try:
        service.react(db_session, review.id, author.id, "love")
        assert False, "expected InvalidReactionError"
    except service.InvalidReactionError:
        pass
