import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EMBEDDING_DIM = 768  # nomic-embed-text's output dimension


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeChunk(Base):
    """One chunk of an ingested PDF, with its embedding. Search ranks by
    cosine similarity computed in Python (see app/rag/service.py) rather
    than pgvector's native <=> operator — simpler and equally testable on
    SQLite at the corpus sizes a telecom knowledge base actually reaches;
    revisit with a native ANN index only if that stops being true."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source: Mapped[str] = mapped_column(String(255))
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
