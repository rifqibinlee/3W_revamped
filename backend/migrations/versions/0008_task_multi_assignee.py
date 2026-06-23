"""Tasks can be assigned to multiple people

Replaces tasks.assignee_id (single FK) with a task_assignees many-to-many
join table. No production data exists yet, so this drops the column
rather than migrating it.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_assignees",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), primary_key=True),
    )
    op.drop_column("tasks", "assignee_id")


def downgrade() -> None:
    op.add_column("tasks", sa.Column("assignee_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True))
    op.drop_table("task_assignees")
