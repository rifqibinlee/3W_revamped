"""capex_pricing_items, reviews, review_comments, review_reactions

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "capex_pricing_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("category", sa.String(10), nullable=False),
        sa.Column("item_name", sa.String(100), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "review_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("review_id", sa.String(36), sa.ForeignKey("reviews.id"), nullable=False),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "review_reactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("review_id", sa.String(36), sa.ForeignKey("reviews.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reaction", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("review_id", "user_id", name="uq_review_reaction_user"),
    )


def downgrade() -> None:
    op.drop_table("review_reactions")
    op.drop_table("review_comments")
    op.drop_table("reviews")
    op.drop_table("capex_pricing_items")
