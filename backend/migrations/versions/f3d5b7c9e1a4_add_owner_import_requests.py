"""owner files waiting for a manager's approval

Revision ID: f3d5b7c9e1a4
Revises: e8b4d2f6a1c3
Create Date: 2026-11-13 13:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "f3d5b7c9e1a4"
down_revision: Union[str, Sequence[str], None] = "e8b4d2f6a1c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STR = sqlmodel.sql.sqltypes.AutoString()


def upgrade() -> None:
    op.create_table(
        "crm_owner_import_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", _STR, nullable=False),
        sa.Column("requested_by_user_id", _STR, nullable=False),
        sa.Column("name", _STR, nullable=False),
        sa.Column("original_filename", _STR, nullable=False),
        sa.Column("sha256", _STR, nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", _STR, nullable=False),
        sa.Column("status", _STR, nullable=False),
        sa.Column("decided_by_user_id", _STR, nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("import_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'approved', 'rejected', 'failed')",
            name="ck_crm_owner_import_request_status",
        ),
        sa.ForeignKeyConstraint(["import_id"], ["crm_contact_imports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("organization_id", "requested_by_user_id", "status"):
        op.create_index(
            op.f(f"ix_crm_owner_import_requests_{column}"), "crm_owner_import_requests", [column]
        )


def downgrade() -> None:
    op.drop_table("crm_owner_import_requests")
