"""persist the Property Finder broker selected for CRM company listings"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "f4b2d8a6c0e1"
down_revision: Union[str, Sequence[str], None] = "e1f5b2c7a940"
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

    for action, references in (
        ("INSERT", "NEW TABLE AS new_rows"),
        ("UPDATE", "OLD TABLE AS old_rows NEW TABLE AS new_rows"),
        ("DELETE", "OLD TABLE AS old_rows"),
    ):
        op.execute(f"""
            CREATE TRIGGER crm_audit_{action.lower()} AFTER {action}
            ON crm_company_listing_sources REFERENCING {references}
            FOR EACH STATEMENT EXECUTE FUNCTION crm_audit_private_mutation()
        """)
    op.execute("""
        CREATE TRIGGER crm_no_truncate BEFORE TRUNCATE ON crm_company_listing_sources
        FOR EACH STATEMENT EXECUTE FUNCTION crm_reject_audit_change()
    """)


def downgrade() -> None:
    op.drop_table("crm_company_listing_sources")
