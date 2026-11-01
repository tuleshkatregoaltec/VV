"""Durable import inputs and worker ownership; results remain in domain import tables."""

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CrmImportJob(SQLModel, table=True):
    __tablename__ = "crm_import_jobs"
    __table_args__ = (
        CheckConstraint(
            "(owner_import_id IS NOT NULL) <> (inbound_import_id IS NOT NULL)",
            name="ck_crm_import_job_target",
        ),
        CheckConstraint(
            "status IN ('queued', 'processing', 'retry_wait', 'completed', 'failed')",
            name="ck_crm_import_job_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10",
            name="ck_crm_import_job_attempts",
        ),
        Index("ix_crm_import_jobs_claim", "status", "available_at", "lease_expires_at"),
        Index("ix_crm_import_jobs_organization", "organization_id"),
    )

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    organization_id: str
    created_by_user_id: str
    owner_import_id: int | None = Field(
        default=None,
        sa_column=Column(ForeignKey("crm_contact_imports.id", ondelete="CASCADE"), unique=True),
    )
    inbound_import_id: int | None = Field(
        default=None,
        sa_column=Column(ForeignKey("crm_inbound_imports.id", ondelete="CASCADE"), unique=True),
    )
    input_object_key: str = Field(unique=True)
    input_sha256: str = Field(sa_column=Column(String(64), nullable=False))
    input_size_bytes: int
    idempotency_key: str = Field(sa_column=Column(String(64), nullable=False))
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )
    status: str = "queued"
    attempt_count: int = 0
    max_attempts: int = 3
    lease_token: str | None = None
    lease_expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    available_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    last_error: str | None = Field(default=None, max_length=200)
