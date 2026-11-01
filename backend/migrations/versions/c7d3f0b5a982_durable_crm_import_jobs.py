"""Queue CRM imports with private input manifests and fenced worker leases.

Revision ID: c7d3f0b5a982
Revises: b6c2e9a4f871
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c7d3f0b5a982"
down_revision = "b6c2e9a4f871"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_import_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("created_by_user_id", sa.String(), nullable=False),
        sa.Column(
            "owner_import_id",
            sa.Integer(),
            sa.ForeignKey("crm_contact_imports.id", ondelete="CASCADE"),
            unique=True,
        ),
        sa.Column(
            "inbound_import_id",
            sa.Integer(),
            sa.ForeignKey("crm_inbound_imports.id", ondelete="CASCADE"),
            unique=True,
        ),
        sa.Column("input_object_key", sa.String(), nullable=False, unique=True),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("input_size_bytes", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(200), nullable=True),
        sa.CheckConstraint(
            "(owner_import_id IS NOT NULL) <> (inbound_import_id IS NOT NULL)",
            name="ck_crm_import_job_target",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'retry_wait', 'completed', 'failed')",
            name="ck_crm_import_job_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10",
            name="ck_crm_import_job_attempts",
        ),
    )
    op.create_index(
        "ix_crm_import_jobs_claim",
        "crm_import_jobs",
        ["status", "available_at", "lease_expires_at"],
    )
    op.create_index("ix_crm_import_jobs_organization", "crm_import_jobs", ["organization_id"])

    # Pre-worker HTTP imports have no durable input to reclaim. Fail visibly
    # instead of leaving pre-deployment crashes in processing forever.
    for table in ("crm_contact_imports", "crm_inbound_imports"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET status = 'failed', completed_at = now(), "
                "error_message = 'Import interrupted before durable jobs were enabled; upload the original file again' "
                "WHERE status = 'processing'"
            )
        )


def downgrade() -> None:
    op.drop_table("crm_import_jobs")
