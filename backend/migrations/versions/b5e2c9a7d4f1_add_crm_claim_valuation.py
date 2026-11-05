"""estimated current value on owner claims (owner valuation, 5 Nov 2026)"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5e2c9a7d4f1"
down_revision: Union[str, Sequence[str], None] = "c4e1a8b7d2f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The shared development database received these columns by hand before this migration
    # ran there (5 Nov 2026), so only add the ones that are missing.
    existing = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("crm_property_contact_claims")
    }
    columns = [
        sa.Column("estimated_value_aed", sa.BigInteger(), nullable=True),
        sa.Column("estimated_value_low_aed", sa.BigInteger(), nullable=True),
        sa.Column("estimated_value_high_aed", sa.BigInteger(), nullable=True),
        sa.Column("valuation", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    ]
    for column in columns:
        if column.name not in existing:
            op.add_column("crm_property_contact_claims", column)


def downgrade() -> None:
    op.drop_column("crm_property_contact_claims", "valuation")
    op.drop_column("crm_property_contact_claims", "estimated_value_high_aed")
    op.drop_column("crm_property_contact_claims", "estimated_value_low_aed")
    op.drop_column("crm_property_contact_claims", "estimated_value_aed")
