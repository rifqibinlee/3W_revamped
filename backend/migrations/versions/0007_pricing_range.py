"""Add admin-only exact price range fields to capex_pricing_items

Two-tier pricing: admin sets the exact price (existing `price` column,
unchanged) plus a price_min/price_max range. Non-admin users are shown
only the range via the API layer (app/pricing/service.py), never the
exact negotiated figure — the columns themselves carry no access
control, that's enforced in the service/router.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("capex_pricing_items", sa.Column("price_min", sa.Float(), nullable=True))
    op.add_column("capex_pricing_items", sa.Column("price_max", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("capex_pricing_items", "price_max")
    op.drop_column("capex_pricing_items", "price_min")
