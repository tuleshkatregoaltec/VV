"""add_user_role_column

Revision ID: abb1a3795b53
Revises:
Create Date: 2025-12-06 15:58:22.982288

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "abb1a3795b53"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users", sa.Column("role", sa.String(20), nullable=False, server_default="user")
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "role")
