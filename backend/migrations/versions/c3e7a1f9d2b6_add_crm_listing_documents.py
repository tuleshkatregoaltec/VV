"""add listing document information and generated documents

Shared development database (stamped at a revision from another branch): apply the same
schema additively, with approval, instead of running alembic there:

    CREATE TABLE IF NOT EXISTS crm_listing_document_info (
        id UUID PRIMARY KEY,
        organization_id VARCHAR NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        source VARCHAR NOT NULL, listing_key VARCHAR NOT NULL, listing_title VARCHAR NOT NULL,
        fields JSON NOT NULL, revision INTEGER NOT NULL,
        created_by_user_id VARCHAR NOT NULL, updated_by_user_id VARCHAR NOT NULL,
        created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_crm_listing_document_info_source
            UNIQUE (organization_id, source, listing_key)
    );
    CREATE INDEX IF NOT EXISTS ix_crm_listing_document_info_organization_id
        ON crm_listing_document_info (organization_id);
    CREATE TABLE IF NOT EXISTS crm_generated_documents (
        id UUID PRIMARY KEY,
        organization_id VARCHAR NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        info_id UUID NOT NULL REFERENCES crm_listing_document_info(id) ON DELETE CASCADE,
        source VARCHAR NOT NULL, listing_key VARCHAR NOT NULL, listing_title VARCHAR NOT NULL,
        doc_type VARCHAR NOT NULL, template_version VARCHAR NOT NULL, snapshot JSON NOT NULL,
        input_revision INTEGER NOT NULL, idempotency_key UUID NOT NULL, status VARCHAR NOT NULL,
        object_key VARCHAR, size_bytes INTEGER, sha256 VARCHAR, failure_code VARCHAR,
        created_by_user_id VARCHAR NOT NULL,
        created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_crm_generated_document_idempotency UNIQUE (organization_id, idempotency_key),
        CONSTRAINT ck_crm_generated_document_type
            CHECK (doc_type IN ('noc', 'brochure', 'lease', 'a2a')),
        CONSTRAINT ck_crm_generated_document_status
            CHECK (status IN ('generating', 'ready', 'failed'))
    );
    CREATE INDEX IF NOT EXISTS ix_crm_generated_documents_organization_id
        ON crm_generated_documents (organization_id);
    CREATE INDEX IF NOT EXISTS ix_crm_generated_documents_listing
        ON crm_generated_documents (organization_id, source, listing_key, created_at);
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "c3e7a1f9d2b6"
down_revision: Union[str, Sequence[str], None] = "f6a8c2d4e9b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_text = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    op.create_table(
        "crm_listing_document_info",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", _text(), nullable=False),
        sa.Column("source", _text(), nullable=False),
        sa.Column("listing_key", _text(), nullable=False),
        sa.Column("listing_title", _text(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", _text(), nullable=False),
        sa.Column("updated_by_user_id", _text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "source", "listing_key", name="uq_crm_listing_document_info_source"
        ),
    )
    op.create_index(
        "ix_crm_listing_document_info_organization_id",
        "crm_listing_document_info",
        ["organization_id"],
    )
    op.create_table(
        "crm_generated_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", _text(), nullable=False),
        sa.Column("info_id", sa.Uuid(), nullable=False),
        sa.Column("source", _text(), nullable=False),
        sa.Column("listing_key", _text(), nullable=False),
        sa.Column("listing_title", _text(), nullable=False),
        sa.Column("doc_type", _text(), nullable=False),
        sa.Column("template_version", _text(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("input_revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("status", _text(), nullable=False),
        sa.Column("object_key", _text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", _text(), nullable=True),
        sa.Column("failure_code", _text(), nullable=True),
        sa.Column("created_by_user_id", _text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["info_id"], ["crm_listing_document_info.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_crm_generated_document_idempotency"
        ),
        sa.CheckConstraint(
            "doc_type IN ('noc', 'brochure', 'lease', 'a2a')", name="ck_crm_generated_document_type"
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'failed')", name="ck_crm_generated_document_status"
        ),
    )
    op.create_index(
        "ix_crm_generated_documents_organization_id",
        "crm_generated_documents",
        ["organization_id"],
    )
    op.create_index(
        "ix_crm_generated_documents_listing",
        "crm_generated_documents",
        ["organization_id", "source", "listing_key", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_generated_documents_listing", table_name="crm_generated_documents")
    op.drop_index(
        "ix_crm_generated_documents_organization_id", table_name="crm_generated_documents"
    )
    op.drop_table("crm_generated_documents")
    op.drop_index(
        "ix_crm_listing_document_info_organization_id", table_name="crm_listing_document_info"
    )
    op.drop_table("crm_listing_document_info")
