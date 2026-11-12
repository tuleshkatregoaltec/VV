import pytest
from pydantic import ValidationError

from app.crm.collection_models import (
    CollectionCreate,
    CollectionItemAdd,
    CollectionResponse,
    PublicCollectionItem,
)

PUBLIC_ITEM_ALLOWED = {
    "status",
    "title",
    "area_name",
    "building_name",
    "property_type",
    "bedrooms",
    "size_sqft",
    "price_aed",
    "mode",
    "rent_period",
    "photos",
    "description",
    "source_label",
    "updated_at",
}


def test_collection_create_rejects_blank_name():
    with pytest.raises(ValidationError):
        CollectionCreate(name="   ")


def test_collection_create_rejects_name_over_120():
    with pytest.raises(ValidationError):
        CollectionCreate(name="x" * 121)


def test_item_add_rejects_unknown_source():
    with pytest.raises(ValidationError):
        CollectionItemAdd(source="bayut", listing_key="abc123")


def test_item_add_rejects_bad_listing_key():
    with pytest.raises(ValidationError):
        CollectionItemAdd(source="property_finder", listing_key="a/b")


def test_collection_response_has_no_token_field():
    assert "share_token" not in CollectionResponse.model_fields


def test_public_item_forbids_private_fields():
    fields = set(PublicCollectionItem.model_fields)
    assert fields <= PUBLIC_ITEM_ALLOWED
    for private in ("agent_name", "agent_phone", "broker_id", "reference", "unit_number"):
        assert private not in fields
