"""queue large owner imports for background processing

Revision ID: d6e1a9c4b7f0
Revises: b2d4f6a8c0e2
Create Date: 2026-11-13 20:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d6e1a9c4b7f0"
down_revision: Union[str, Sequence[str], None] = "b2d4f6a8c0e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_crm_owner_import_request_status", "crm_owner_import_requests")
    op.create_check_constraint(
        "ck_crm_owner_import_request_status",
        "crm_owner_import_requests",
        "status IN ('pending', 'queued', 'processing', 'approved', 'rejected', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_crm_owner_import_request_status", "crm_owner_import_requests")
    op.create_check_constraint(
        "ck_crm_owner_import_request_status",
        "crm_owner_import_requests",
        "status IN ('pending', 'processing', 'approved', 'rejected', 'failed')",
    )
