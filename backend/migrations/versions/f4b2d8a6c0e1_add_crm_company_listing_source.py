"""persist the Property Finder broker selected for CRM company listings"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "f4b2d8a6c0e1"
down_revision: Union[str, Sequence[str], None] = "9a3c1f4d7b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_company_listing_sources",
        sa.Column("organization_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("broker_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("broker_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("selected_by_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id"),
    )


def downgrade() -> None:
    op.drop_table("crm_company_listing_sources")
