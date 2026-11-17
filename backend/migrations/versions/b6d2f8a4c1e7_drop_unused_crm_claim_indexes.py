"""drop three CRM claim indexes no query can use

Revision ID: b6d2f8a4c1e7
Revises: 9c3f5a7d1e24
Create Date: 2026-11-15 19:00:00.000000

Production statistics (pg_stat_user_indexes, no reset since the 2026-11-06 start, so at least
nine days of owner-registry traffic) show zero scans for all three, and the code never asks
for what they order or filter by:

* ix_crm_claim_owner_property_preference and ix_crm_claim_list_owner_property_preference
  (38 MB + 41 MB on crm_property_contact_claims) order by
  ``preference DESC, confidence_score DESC, transaction_date DESC``. The only reader
  (``app.crm.owner_repository``, DISTINCT ON owner/property) sorts by
  ``(status_rank >= 4) DESC, CASE WHEN status_rank >= 4 THEN transaction_date END DESC, ...``
  over a CTE, an ordering these indexes can never supply. Every import rewrites the table, and
  each index is maintained on every insert and update.
* ix_crm_assessed_claim_lead (6 MB, partial) on crm_owner_assessed_claims: nothing filters
  assessed claims by lead_id; the column is only stored and read back.

Kept on purpose: ix_crm_assessed_claim_list (117 MB, also 0 scans) is the access path of the
Owners list queries (``organization_id, generation, list_id`` in app.crm.owner_store);
EXPLAIN on a real list picks it, the zero is a quiet window, not an unused path.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b6d2f8a4c1e7"
down_revision: Union[str, Sequence[str], None] = "9c3f5a7d1e24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PREFERENCE_EXPRESSION = """(
    CASE ownership_status
        WHEN 'former_owner' THEN 6
        WHEN 'verified_current_owner' THEN 5
        WHEN 'probable_current_owner' THEN 4
        WHEN 'unit_linked_unverified' THEN 3
        WHEN 'conflicting_claim' THEN 2
        ELSE 1
    END
)"""


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_crm_claim_list_owner_property_preference")
    op.execute("DROP INDEX IF EXISTS ix_crm_claim_owner_property_preference")
    op.execute("DROP INDEX IF EXISTS ix_crm_assessed_claim_lead")


def downgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_crm_assessed_claim_lead
        ON crm_owner_assessed_claims (organization_id, generation, lead_id)
        WHERE lead_id IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_crm_claim_owner_property_preference
        ON crm_property_contact_claims (
            organization_id, owner_key, property_key,
            {_PREFERENCE_EXPRESSION} DESC, confidence_score DESC, transaction_date DESC NULLS LAST
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS ix_crm_claim_list_owner_property_preference
        ON crm_property_contact_claims (
            organization_id, list_id, owner_key, property_key,
            {_PREFERENCE_EXPRESSION} DESC, confidence_score DESC, transaction_date DESC NULLS LAST
        )
        """
    )
