from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.crm import inbound
from app.crm.import_models import CrmPropertyContactClaim
from app.crm.inbound_models import CrmInboundContact


def _claim(number, name="Example Person"):
    now = datetime.now(timezone.utc)
    return CrmPropertyContactClaim(
        id=number,
        organization_id="org",
        import_id=1,
        list_id=1,
        source_sheet="Owners",
        source_row_number=number,
        row_fingerprint=str(number),
        owner_key=str(number),
        property_key=f"tower|{number}",
        contact_name=name,
        phone_primary="+971501234567",
        area_name="Area",
        building_name="Tower",
        unit_number=str(number),
        ownership_status="verified_current_owner",
        confidence_score=98,
        match_reason="Old saved assessment",
        created_at=now,
        updated_at=now,
    )


def _contact():
    now = datetime.now(timezone.utc)
    return CrmInboundContact(
        id=1,
        organization_id="org",
        full_name="Example Person",
        phone="+971501234567",
        created_at=now,
        updated_at=now,
    )


def _assessment(claims, statuses, invalid_ids=()):
    rows = []
    for claim, status in zip(claims, statuses, strict=True):
        row = claim.model_dump()
        row.update(
            canonical_owner_key=claim.owner_key,
            property_identity=None if claim.id in invalid_ids else ("area", claim.property_key),
            assessed_status=status,
            assessed_reason="Fresh shared assessment",
            assessed_confidence_score=95,
        )
        rows.append(row)
    return SimpleNamespace(rows=rows)


async def test_inbound_priority_uses_current_assessment_and_excludes_invalid_properties(
    monkeypatch,
):
    claims = [_claim(1), _claim(2)]
    monkeypatch.setattr(
        inbound.inbound_repository, "find_identity_claims", AsyncMock(return_value=claims)
    )
    assessment = AsyncMock(
        return_value=_assessment(claims, ["former_owner", "insufficient_property_data"], {2})
    )
    monkeypatch.setattr(inbound, "get_owner_assessment", assessment)
    result = await inbound._bulk_ownership_enrichments(
        None, organization_id="org", contacts=[_contact()]
    )
    assert result[1].former_owner
    assert not result[1].current_owner
    assert result[1].known_property_count == 1
    assert claims[0].ownership_status == "verified_current_owner", (
        "Reading must not mutate saved evidence"
    )
    assert assessment.await_args.kwargs["organization_id"] == "org"


async def test_shared_phone_does_not_give_an_inbound_contact_someone_elses_holdings(monkeypatch):
    claims = [_claim(1, "Different Person")]
    monkeypatch.setattr(
        inbound.inbound_repository, "find_identity_claims", AsyncMock(return_value=claims)
    )
    monkeypatch.setattr(
        inbound,
        "get_owner_assessment",
        AsyncMock(return_value=_assessment(claims, ["verified_current_owner"])),
    )
    assert (
        await inbound._bulk_ownership_enrichments(
            None, organization_id="org", contacts=[_contact()]
        )
        == {}
    )


async def test_inbound_registry_detail_agrees_with_shared_assessment(monkeypatch):
    claims = [_claim(1), _claim(2, "Different Person")]
    monkeypatch.setattr(
        inbound.inbound_repository, "find_contact_claims", AsyncMock(return_value=claims)
    )
    monkeypatch.setattr(
        inbound,
        "get_owner_assessment",
        AsyncMock(
            return_value=_assessment(claims, ["conflicting_claim", "verified_current_owner"])
        ),
    )
    monkeypatch.setattr(inbound, "_registry_transaction_evidence", AsyncMock(return_value=({}, {})))
    profiles = await inbound._registry_profiles(None, contact=_contact(), criteria={})
    assert len(profiles) == 1
    assert profiles[0].ownership_status == "conflicting_claim"
    assert profiles[0].contact_name == "Example Person"
