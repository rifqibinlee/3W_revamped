"""chat tables, and the FK on annotations.conversation_id deferred since 0002

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("is_group", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "conversation_participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("sender_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "message_reads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
    )

    # The FK on annotations.conversation_id was deferred in 0002 since
    # conversations didn't exist yet — added now that it does.
    op.create_foreign_key(
        "fk_annotations_conversation_id", "annotations", "conversations", ["conversation_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_annotations_conversation_id", "annotations", type_="foreignkey")
    op.drop_table("message_reads")
    op.drop_table("messages")
    op.drop_table("conversation_participants")
    op.drop_table("conversations")
