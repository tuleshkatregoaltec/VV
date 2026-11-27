"""Allow the CRM to generate Sell & Switch studies."""

from typing import Sequence, Union

from alembic import op

revision: str = "d4a7c2e9f1b6"
down_revision: Union[str, Sequence[str], None] = "c5e9a3b7d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_crm_generated_document_type", "crm_generated_documents", type_="check"
    )
    op.create_check_constraint(
        "ck_crm_generated_document_type",
        "crm_generated_documents",
        "doc_type IN ('noc', 'brochure', 'lease', 'a2a', 'sell_switch')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_crm_generated_document_type", "crm_generated_documents", type_="check"
    )
    op.create_check_constraint(
        "ck_crm_generated_document_type",
        "crm_generated_documents",
        "doc_type IN ('noc', 'brochure', 'lease', 'a2a')",
    )
