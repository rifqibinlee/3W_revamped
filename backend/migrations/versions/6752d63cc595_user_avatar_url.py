"""user_avatar_url

Revision ID: 6752d63cc595
Revises: 0008
Create Date: 2026-06-28 22:20:37.794276

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6752d63cc595'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Autogenerate also wanted to drop projects_conversation_id_fkey —
    pre-existing drift between the live DB and the Project model (which
    has deliberately declared conversation_id with no FK for a while
    now, see the model's docstring), unrelated to this change. Left
    alone here rather than bundled into an avatar-column migration.
    """
    op.add_column('users', sa.Column('avatar_url', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'avatar_url')
