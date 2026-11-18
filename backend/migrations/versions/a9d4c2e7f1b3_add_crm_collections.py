"""add shareable CRM property collections"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "a9d4c2e7f1b3"
down_revision: Union[str, Sequence[str], None] = "c3e7a1f9d2b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crm_collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_by_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("share_token", sqlmodel.sql.sqltypes.AutoString(length=43), nullable=False),
        sa.Column("sharing_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("agent_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("agent_email", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("agent_phone", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_crm_collections_id_org"),
    )
    op.create_index(
        op.f("ix_crm_collections_organization_id"), "crm_collections", ["organization_id"]
    )
    op.create_index(
        op.f("ix_crm_collections_share_token"), "crm_collections", ["share_token"], unique=True
    )
    op.create_table(
        "crm_collection_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("listing_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("listing_title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("added_by_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id", "organization_id"],
            ["crm_collections.id", "crm_collections.organization_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "collection_id", "source", "listing_key", name="uq_crm_collection_item_listing"
        ),
    )
    op.create_index(
        "ix_crm_collection_items_collection",
        "crm_collection_items",
        ["collection_id", "added_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_crm_collection_items_collection", table_name="crm_collection_items")
    op.drop_table("crm_collection_items")
    op.drop_index(op.f("ix_crm_collections_share_token"), table_name="crm_collections")
    op.drop_index(op.f("ix_crm_collections_organization_id"), table_name="crm_collections")
    op.drop_table("crm_collections")
