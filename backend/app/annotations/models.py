import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


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


class Annotation(Base):
    """A map annotation that doubles as a lightweight PM tool: unassigned
    (assignee_id is NULL) it's just a note; assigning it converts it into
    a task with a due date, status, and review workflow.

    geometry is stored as JSON (lat/lng or a GeoJSON-shaped dict) rather
    than a real PostGIS geometry column — PostGIS isn't wired up yet (see
    docs/adr/0001-architecture.md); this becomes spatially queryable once
    that lands, without changing the API shape.

    conversation_id has no FK constraint yet since the chat module's
    tables don't exist — added as a plain nullable column now, the FK
    constraint will be added in a later migration once Chat is built.
    """

    __tablename__ = "annotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    geometry: Mapped[dict] = mapped_column(JSON)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True)

    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AnnotationComment(Base):
    __tablename__ = "annotation_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    annotation_id: Mapped[str] = mapped_column(ForeignKey("annotations.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
