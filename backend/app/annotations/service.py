from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.annotations.models import Annotation, Project, ProjectComment, Task, TaskStatus, task_assignees
from app.auth.models import Role, User
from app.chat import service as chat_service


class NotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class NotAProjectError(Exception):
    """Raised when trying to create a task under a note (no assignee) —
    there's no one to delegate the work to."""

    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(project_id)
    return project


def get_task(db: Session, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise NotFoundError(task_id)
    return task


def get_annotation(db: Session, annotation_id: str) -> Annotation:
    annotation = db.get(Annotation, annotation_id)
    if annotation is None:
        raise NotFoundError(annotation_id)
    return annotation


def delete_annotation(db: Session, annotation: Annotation) -> None:
    db.delete(annotation)
    db.commit()


def delete_project(db: Session, project: Project) -> None:
    """Super-Admin-only — deletes the project along with everything that
    references it (annotations, tasks + their assignee links, comments),
    since none of those are useful orphaned. task_assignees rows must go
    before their tasks — the FK has no ON DELETE CASCADE."""
    task_ids = [t.id for t in db.query(Task.id).filter(Task.project_id == project.id)]
    if task_ids:
        db.execute(task_assignees.delete().where(task_assignees.c.task_id.in_(task_ids)))
    db.query(Annotation).filter(Annotation.project_id == project.id).delete()
    db.query(Task).filter(Task.project_id == project.id).delete()
    db.query(ProjectComment).filter(ProjectComment.project_id == project.id).delete()
    db.delete(project)
    db.commit()


def create_project(
    db: Session,
    creator: User,
    title: str,
    description: str | None = None,
    assignee_id: str | None = None,
) -> Project:
    """Creates a note (assignee_id=None) or a project (assignee_id set) —
    same entity, the only difference is whether assignee_id is populated.
    Assigning at creation time auto-creates the project's chat room."""
    conversation_id = None
    if assignee_id:
        conversation_id = chat_service.get_or_create_direct_conversation(db, creator.id, assignee_id).id

    project = Project(
        creator_id=creator.id, title=title, description=description,
        assignee_id=assignee_id, conversation_id=conversation_id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def list_projects(db: Session) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc())))


def assign_project(db: Session, project: Project, assignee_id: str) -> Project:
    """Converts a note into a project (or reassigns an existing one),
    auto-creating/reusing the chat room with the new assignee."""
    project.assignee_id = assignee_id
    project.conversation_id = chat_service.get_or_create_direct_conversation(
        db, project.creator_id, assignee_id
    ).id
    db.commit()
    db.refresh(project)
    return project


def add_annotation(db: Session, project: Project, creator: User, geometry: dict, label: str | None = None) -> Annotation:
    annotation = Annotation(project_id=project.id, creator_id=creator.id, geometry=geometry, label=label)
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return annotation


def list_annotations(db: Session, project_id: str) -> list[Annotation]:
    return list(db.scalars(select(Annotation).where(Annotation.project_id == project_id)))


def create_task(
    db: Session, project: Project, creator: User, title: str, assignee_ids: list[str], due_date: datetime,
    description: str | None = None,
) -> Task:
    if not project.assignee_id:
        raise NotAProjectError("cannot create a task under a note — assign the project to someone first")

    assignees = list(db.scalars(select(User).where(User.id.in_(assignee_ids))))
    task = Task(
        project_id=project.id, creator_id=creator.id, title=title, description=description,
        assignees=assignees, due_date=due_date, status=TaskStatus.TODO,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def list_tasks(db: Session, project_id: str | None = None, assignee_id: str | None = None) -> list[Task]:
    stmt = select(Task)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if assignee_id:
        stmt = stmt.where(Task.assignees.any(User.id == assignee_id))
    return list(db.scalars(stmt))


def _require_status(task: Task, expected: str) -> None:
    if task.status != expected:
        raise InvalidTransitionError(f"expected status {expected!r}, got {task.status!r}")


def _is_assignee(task: Task, actor: User) -> bool:
    return any(a.id == actor.id for a in task.assignees)


def start_progress(db: Session, task: Task, actor: User) -> Task:
    if not _is_assignee(task, actor):
        raise PermissionDeniedError("only an assignee can start progress on this task")
    _require_status(task, TaskStatus.TODO)
    task.status = TaskStatus.IN_PROGRESS
    db.commit()
    db.refresh(task)
    return task


def submit_for_review(db: Session, task: Task, actor: User) -> Task:
    if not _is_assignee(task, actor):
        raise PermissionDeniedError("only an assignee can submit this task for review")
    _require_status(task, TaskStatus.IN_PROGRESS)
    task.status = TaskStatus.PENDING_REVIEW
    db.commit()
    db.refresh(task)
    return task


def _require_reviewer(task: Task, actor: User) -> None:
    """The assigner is whoever created the task, or an admin acting on
    their behalf — an assignee can never review their own task."""
    if _is_assignee(task, actor):
        raise PermissionDeniedError("an assignee cannot review their own task")
    if task.creator_id != actor.id and actor.role != Role.ADMIN:
        raise PermissionDeniedError("only the task's creator (or an admin) can review it")


def approve(db: Session, task: Task, actor: User) -> Task:
    _require_reviewer(task, actor)
    _require_status(task, TaskStatus.PENDING_REVIEW)
    task.status = TaskStatus.DONE
    task.reviewed_by_id = actor.id
    task.reviewed_at = _now()
    task.rejection_reason = None
    db.commit()
    db.refresh(task)
    return task


def reject(db: Session, task: Task, actor: User, reason: str) -> Task:
    _require_reviewer(task, actor)
    _require_status(task, TaskStatus.PENDING_REVIEW)
    task.status = TaskStatus.IN_PROGRESS
    task.reviewed_by_id = actor.id
    task.reviewed_at = _now()
    task.rejection_reason = reason
    db.commit()
    db.refresh(task)
    return task


def add_comment(db: Session, project: Project, author: User, body: str) -> ProjectComment:
    comment = ProjectComment(project_id=project.id, author_id=author.id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def list_comments(db: Session, project_id: str) -> list[ProjectComment]:
    return list(
        db.scalars(select(ProjectComment).where(ProjectComment.project_id == project_id).order_by(ProjectComment.created_at))
    )


def gantt_rows(db: Session, assignee_id: str | None = None, project_id: str | None = None) -> list[Task]:
    """Simple due-date timeline, no dependency graph: each row is one
    task spanning created_at -> due_date for its assignee."""
    return list_tasks(db, project_id=project_id, assignee_id=assignee_id)
