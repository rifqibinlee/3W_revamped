from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.annotations.models import Annotation, AnnotationComment, TaskStatus
from app.auth.models import Role, User


class NotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_annotation(db: Session, annotation_id: str) -> Annotation:
    annotation = db.get(Annotation, annotation_id)
    if annotation is None:
        raise NotFoundError(annotation_id)
    return annotation


def create_annotation(
    db: Session,
    creator: User,
    title: str,
    geometry: dict,
    description: str | None = None,
    priority: str | None = None,
    assignee_id: str | None = None,
    due_date: datetime | None = None,
) -> Annotation:
    """Creates a note (assignee_id=None) or a task (assignee_id set,
    status starts at TODO) — same entity, the only difference is whether
    assignee_id is populated."""
    annotation = Annotation(
        creator_id=creator.id,
        title=title,
        description=description,
        geometry=geometry,
        priority=priority,
        assignee_id=assignee_id,
        due_date=due_date,
        status=TaskStatus.TODO if assignee_id else None,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return annotation


def assign_task(db: Session, annotation: Annotation, assignee_id: str, due_date: datetime) -> Annotation:
    """Converts a note into a task. Re-assigning an existing task (rather
    than a bare note) resets it back to TODO — picking up a task at a new
    assignee shouldn't inherit the old assignee's in-progress/review state."""
    annotation.assignee_id = assignee_id
    annotation.due_date = due_date
    annotation.status = TaskStatus.TODO
    annotation.reviewed_by_id = None
    annotation.reviewed_at = None
    annotation.rejection_reason = None
    db.commit()
    db.refresh(annotation)
    return annotation


def _require_status(annotation: Annotation, expected: str) -> None:
    if annotation.status != expected:
        raise InvalidTransitionError(f"expected status {expected!r}, got {annotation.status!r}")


def start_progress(db: Session, annotation: Annotation, actor: User) -> Annotation:
    if annotation.assignee_id != actor.id:
        raise PermissionDeniedError("only the assignee can start progress on this task")
    _require_status(annotation, TaskStatus.TODO)
    annotation.status = TaskStatus.IN_PROGRESS
    db.commit()
    db.refresh(annotation)
    return annotation


def submit_for_review(db: Session, annotation: Annotation, actor: User) -> Annotation:
    if annotation.assignee_id != actor.id:
        raise PermissionDeniedError("only the assignee can submit this task for review")
    _require_status(annotation, TaskStatus.IN_PROGRESS)
    annotation.status = TaskStatus.PENDING_REVIEW
    db.commit()
    db.refresh(annotation)
    return annotation


def _require_reviewer(annotation: Annotation, actor: User) -> None:
    """The assigner is whoever created the task, or an admin acting on
    their behalf — the assignee can never review their own work."""
    if actor.id == annotation.assignee_id:
        raise PermissionDeniedError("the assignee cannot review their own task")
    if annotation.creator_id != actor.id and actor.role != Role.ADMIN:
        raise PermissionDeniedError("only the task's creator (or an admin) can review it")


def approve(db: Session, annotation: Annotation, actor: User) -> Annotation:
    _require_reviewer(annotation, actor)
    _require_status(annotation, TaskStatus.PENDING_REVIEW)
    annotation.status = TaskStatus.DONE
    annotation.reviewed_by_id = actor.id
    annotation.reviewed_at = _now()
    annotation.rejection_reason = None
    db.commit()
    db.refresh(annotation)
    return annotation


def reject(db: Session, annotation: Annotation, actor: User, reason: str) -> Annotation:
    _require_reviewer(annotation, actor)
    _require_status(annotation, TaskStatus.PENDING_REVIEW)
    annotation.status = TaskStatus.IN_PROGRESS
    annotation.reviewed_by_id = actor.id
    annotation.reviewed_at = _now()
    annotation.rejection_reason = reason
    db.commit()
    db.refresh(annotation)
    return annotation


def add_comment(db: Session, annotation: Annotation, author: User, body: str) -> AnnotationComment:
    comment = AnnotationComment(annotation_id=annotation.id, author_id=author.id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def gantt_rows(db: Session, assignee_id: str | None = None) -> list[Annotation]:
    """Simple due-date timeline, no dependency graph: each row is one
    task spanning created_at -> due_date for its assignee."""
    stmt = select(Annotation).where(Annotation.assignee_id.is_not(None))
    if assignee_id:
        stmt = stmt.where(Annotation.assignee_id == assignee_id)
    return list(db.scalars(stmt))
