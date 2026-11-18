"""join crm collections and lead assignment chains

Revision ID: e1f3a5c7b9d2
Revises: a9d4c2e7f1b3, d6e1a9c4b7f0
Create Date: 2026-11-18 11:46:27.091167

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "e1f3a5c7b9d2"
down_revision: Union[str, Sequence[str], None] = ("a9d4c2e7f1b3", "d6e1a9c4b7f0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
