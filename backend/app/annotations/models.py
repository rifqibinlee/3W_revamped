import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.models import User
from app.core.db import Base

task_assignees = Table(
    "task_assignees",
    Base.metadata,
    Column("task_id", ForeignKey("tasks.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus:
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"
    DONE = "done"
    REJECTED = "rejected"


class Project(Base):
    """The grouping container for map annotations and, once assigned, for
    tasks: no assignee = a plain note, assignee set = a project. Multiple
    Annotations (map shapes) belong to one Project. Discussion/comments
    live here at the project level, not per-annotation.

    conversation_id is the project's chat room, auto-created the moment
    it gets an assignee (note -> project). No FK constraint to
    conversations — same reasoning as before, kept loosely coupled."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Annotation(Base):
    """A single map shape (point/line/polygon/buffer) belonging to a
    Project. Pure geometry + a label — no task-like fields here anymore,
    those live on Task now.

    geometry is stored as JSON rather than a real PostGIS column —
    PostGIS isn't wired up yet (see docs/adr/0001-architecture.md); this
    becomes spatially queryable once that lands, without changing the
    API shape."""

    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    geometry: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Task(Base):
    """A work item inside a Project. Only projects (assignee_id set) can
    have tasks — there's no one to delegate a note's work to, so creating
    a task under a note is rejected at the service layer.

    Tasks can be assigned to multiple people (e.g. a survey needing both
    a field tech and a planner) — `assignees` is a many-to-many via
    task_assignees, not a single FK."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    assignees: Mapped[list[User]] = relationship(User, secondary=task_assignees)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default=TaskStatus.TODO)

    @property
    def assignee_ids(self) -> list[str]:
        return [a.id for a in self.assignees]

    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ProjectComment(Base):
    """Discussion thread on a project (or note) — moved up from the old
    per-annotation comments, since 'the discussion is project level'."""

    __tablename__ = "project_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
