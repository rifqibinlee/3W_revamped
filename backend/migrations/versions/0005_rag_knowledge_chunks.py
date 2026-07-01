"""knowledge_chunks table for FTS-based RAG (no pgvector)

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(512), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # GIN index for fast full-text search via to_tsvector
    op.execute(
        "CREATE INDEX knowledge_chunks_fts_idx ON knowledge_chunks "
        "USING GIN (to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.drop_index("knowledge_chunks_fts_idx", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
