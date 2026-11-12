"""Shareable property collections: a named set of managed listings an agent can share by link.

The share token lives only on the table row; no response model carries it. The public contracts
list exactly what a client may see, so anything not named there cannot leak.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints
from sqlalchemy import DateTime, ForeignKeyConstraint, Index, UniqueConstraint
from sqlmodel import Column, SQLModel
from sqlmodel import Field as SQLField

from app.crm.document_models import LISTING_KEY_PATTERN, ListingKey
from app.crm.models import CrmCompanyListingDetail

__all__ = ["LISTING_KEY_PATTERN", "ListingKey"]

Source = Literal["property_finder"]
MAX_COLLECTION_ITEMS = 50

CollectionName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
ContactText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class CrmCollection(SQLModel, table=True):
    """One shareable collection, owned by an organization."""

    __tablename__ = "crm_collections"
    __table_args__ = (
        # Anchors the composite foreign key so an item cannot name another organization.
        UniqueConstraint("id", "organization_id", name="uq_crm_collections_id_org"),
    )

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    organization_id: str = SQLField(foreign_key="organizations.id", ondelete="CASCADE", index=True)
    created_by_user_id: str
    name: str
    share_token: str = SQLField(unique=True, index=True, max_length=43)
    sharing_enabled: bool = False
    agent_name: str
    agent_email: str | None = None
    agent_phone: str | None = None
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmCollectionItem(SQLModel, table=True):
    """A listing in a collection; the title is a snapshot for the agent UI only."""

    __tablename__ = "crm_collection_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "organization_id"],
            ["crm_collections.id", "crm_collections.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "collection_id", "source", "listing_key", name="uq_crm_collection_item_listing"
        ),
        Index("ix_crm_collection_items_collection", "collection_id", "added_at"),
    )

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    collection_id: UUID
    organization_id: str
    source: str
    listing_key: str
    listing_title: str
    added_by_user_id: str
    added_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CollectionCreate(_Input):
    name: CollectionName


class CollectionUpdate(_Input):
    name: CollectionName | None = None
    sharing_enabled: bool | None = None
    agent_name: ContactText | None = None
    agent_email: EmailStr | None = None
    agent_phone: ContactText | None = None


class CollectionItemAdd(_Input):
    source: Source
    listing_key: ListingKey


class CollectionItemResponse(BaseModel):
    id: UUID
    source: str
    listing_key: str
    listing_title: str
    added_at: datetime
    # None when the listing is no longer in the managed inventory.
    listing: CrmCompanyListingDetail | None = None


class CollectionResponse(BaseModel):
    """Management view. Deliberately has no token field; see ShareLinkResponse."""

    id: UUID
    name: str
    sharing_enabled: bool
    item_count: int
    created_by_user_id: str
    agent_name: str
    agent_email: str | None
    agent_phone: str | None
    created_at: datetime
    updated_at: datetime


class CollectionDetailResponse(CollectionResponse):
    items: list[CollectionItemResponse]


class CollectionListResponse(BaseModel):
    items: list[CollectionResponse]
    total: int
    limit: int
    offset: int


class ShareLinkResponse(BaseModel):
    url: str


class PublicCollectionAgent(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None


class PublicCollectionItem(BaseModel):
    """What a client sees for one property. An unavailable item carries no other fields."""

    status: Literal["available", "unavailable"]
    title: str | None = None
    area_name: str | None = None
    building_name: str | None = None
    property_type: str | None = None
    bedrooms: int | None = None
    size_sqft: float | None = None
    price_aed: int | None = None
    mode: str | None = None
    rent_period: Literal["yearly"] | None = None
    photos: list[str] = Field(default_factory=list)
    description: str | None = None
    source_label: str = "Property Finder"
    updated_at: datetime | None = None


class PublicCollectionResponse(BaseModel):
    name: str
    agent: PublicCollectionAgent
    items: list[PublicCollectionItem]
    fetched_at: datetime
