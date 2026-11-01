"""Metadata-only, transactionally appended private CRM mutation records."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, text
from sqlmodel import Column, Field, SQLModel


class CrmMutationAudit(SQLModel, table=True):
    __tablename__ = "crm_mutation_audit"
    __table_args__ = (
        Index("ix_crm_mutation_audit_org_time", "organization_id", "occurred_at"),
        CheckConstraint("row_count > 0", name="ck_crm_mutation_audit_rows"),
        CheckConstraint(
            "action IN ('INSERT', 'UPDATE', 'DELETE')", name="ck_crm_mutation_audit_action"
        ),
        CheckConstraint("actor_kind IN ('user', 'database')", name="ck_crm_mutation_audit_actor"),
        CheckConstraint("outcome = 'success'", name="ck_crm_mutation_audit_outcome"),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    organization_id: str
    actor_id: str
    actor_kind: str
    database_actor: str
    request_id: str | None = None
    action: str
    resource: str
    outcome: str = Field(default="success", sa_column_kwargs={"server_default": "success"})
    row_count: int = Field(sa_type=BigInteger)
    occurred_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("clock_timestamp()")
        )
    )
