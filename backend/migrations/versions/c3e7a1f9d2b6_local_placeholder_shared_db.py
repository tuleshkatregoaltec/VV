"""LOCAL PLACEHOLDER - do not commit (12 Nov 2026).

The shared development database (and its local restore) is stamped at c3e7a1f9d2b6, a
teammate's migration from vitevue/vitevue-platform that is not in this branch. Beyond
f6a8c2d4e9b1 it holds crm_company_listings, crm_generated_documents,
crm_listing_document_info, uq_crm_inbound_owner_db_recent_sale, ix_crm_claim_org_party_date
and text-typed news_articles columns. This no-op lets `alembic upgrade head` run. Delete this
file, and point d2a6e8c4b1f7 at the real revision, as soon as that migration is merged in.
"""

from typing import Sequence, Union

revision: str = "c3e7a1f9d2b6"
down_revision: Union[str, Sequence[str], None] = "f6a8c2d4e9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
