"""An import and a rematch both decide through the property-first matcher (ClickHouse mocked)."""

import io
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import UploadFile
from sqlmodel import select

from app.crm import imports, owner_queries, owners, ownership
from app.crm.import_models import CrmContactImport, CrmPropertyContactClaim
from app.crm.owner_matcher import MATCHER_VERSION

HEADERS = (
    "NameEn,BuildingNameEn,Project,Master Project,UnitNumber,PropertyTypeEn,Regis,"
    "ProcedureValue,ProcedurePartyTypeNameEn,ProcedureNameEn,Size"
)
ROWS = [
    # 2: bought unit 101, which sold again later: a former owner
    "Early Buyer,Alpha Tower,Alpha,Business Bay,101,Apartment,2024-01-01,1000000,Buyer,Sale,100",
    # 3 and 4: both parties of the same unit 102 sale
    "Seller Two,Alpha Tower,Alpha,Business Bay,102,Apartment,2024-02-01,1500000,Seller,Sale,100",
    "Buyer Two,Alpha Tower,Alpha,Business Bay,102,Apartment,2024-02-01,1500000,Buyer,Sale,100",
    # 5 and 6: a mortgage registered the day unit 103 was bought; its Buyer is the bank
    "Borrower,Alpha Tower,Alpha,Business Bay,103,Apartment,2024-03-01,2400000,Seller,"
    "Mortgage Registration,100",
    "Emirates NBD Bank PJSC,Alpha Tower,Alpha,Business Bay,103,Apartment,2024-03-01,2400000,"
    "Buyer,Mortgage Registration,100",
    # 7: a unit DXBI does not have
    "Nobody,Alpha Tower,Alpha,Business Bay,999,Apartment,2024-03-01,777000,Buyer,Sale,100",
]
WANT = {
    2: ("matched_sale", "green", "former_owner"),
    3: ("matched_sale", "green", "former_owner"),
    4: ("matched_sale", "green", "verified_current_owner"),
    5: ("matched_sale_via_mortgage", "green", "verified_current_owner"),
    6: ("lender", "grey", "unmatched"),
    7: ("no_evidence", "grey", "unmatched"),
}


def sale(unit: str, amount: int, day: str) -> dict:
    return {
        "family": "sale",
        "event_key": f"sale-{unit}-{day}",
        "event_date": day,
        "amount": amount,
        "unit_number": unit,
        "area_name": "Business Bay",
        "project_name": "Alpha",
        "building_name": "Alpha Tower",
        "size_sqft": 1076.4,
        "property_type": "Apartment",
    }


def warehouse(monkeypatch):
    """The ClickHouse reads of the property-first stage and the assessment, mocked."""
    place = {
        "family": "sale",
        "area_name": "Business Bay",
        "project_name": "Alpha",
        "building_name": "Alpha Tower",
        "location_name": "",
    }
    hierarchy = [
        {"name_key": "businessbay", "community_key": "businessbay", "project_key": ""},
        {"name_key": "alphatower", "community_key": "businessbay", "project_key": "alpha"},
    ]
    events = [
        sale("101", 1_000_000, "2024-01-01"),
        sale("101", 2_000_000, "2025-06-01"),
        sale("102", 1_500_000, "2024-02-01"),
        sale("103", 3_000_000, "2024-03-01"),
    ]
    for name, value in {
        "fetch_place_hierarchy": hierarchy,
        "fetch_registry_places": [],
        "fetch_matcher_places": [place],
        "fetch_matcher_events": events,
        "fetch_matcher_registry": [],
        "fetch_assessment_building_aliases": [],
        "fetch_assessment_sales": [],
    }.items():
        monkeypatch.setattr(owner_queries, name, AsyncMock(return_value=value))


def legacy_stages(monkeypatch):
    """The legacy lookups find nothing: every verdict below comes from the new matcher."""
    monkeypatch.setattr(imports, "_llm_mapping", AsyncMock(side_effect=lambda profile: profile))
    for module in (imports, ownership):
        for name in (
            "prepare_file_context",
            "_recover_property_identity_from_transaction",
            "_recover_property_identity_from_near_transaction",
            "recover_from_file_context",
            "_apply_registry_unit_fallbacks",
        ):
            monkeypatch.setattr(module, name, AsyncMock(return_value={}))
        monkeypatch.setattr(module, "_sales_evidence", AsyncMock(return_value={}))
        monkeypatch.setattr(module, "_rental_evidence", AsyncMock(return_value={}))
    monkeypatch.setattr(imports, "_enrich_workspaces", AsyncMock())
    monkeypatch.setattr(imports, "save_drop_log", AsyncMock(return_value=True))


async def claims_of(session, import_id):
    session.expire_all()
    rows = (
        await session.exec(
            select(CrmPropertyContactClaim)
            .where(CrmPropertyContactClaim.import_id == import_id)
            .order_by(CrmPropertyContactClaim.source_row_number)
        )
    ).all()
    return {claim.source_row_number: claim for claim in rows}


def check_claims(claims):
    for row, (outcome, colour, status) in WANT.items():
        match = claims[row].evidence["owner_match"]
        assert (match["outcome"], match["colour"], claims[row].ownership_status) == (
            outcome,
            colour,
            status,
        ), row
        assert match["version"] == MATCHER_VERSION
    sale_match = claims[4].evidence["owner_match"]
    assert sale_match["sale"]["amount_aed"] == 1_500_000
    assert sale_match["sale"]["date"] == "2024-02-01" and sale_match["sale"]["source"] == "DXBI"
    assert claims[2].later_sale_date is not None and claims[2].later_sale_date.year == 2025
    assert claims[4].later_sale_date is None
    assert claims[5].evidence["owner_match"]["sale"]["amount_aed"] == 3_000_000


async def test_an_import_decides_through_the_property_first_matcher(
    pg_session, monkeypatch, property_first_matcher
):
    legacy_stages(monkeypatch)
    warehouse(monkeypatch)
    org = str(uuid4())
    csv = "\n".join([HEADERS, *ROWS]).encode()
    response = await imports._execute_contact_import(
        pg_session,
        upload=UploadFile(file=io.BytesIO(csv), filename="alpha.csv"),
        name="Alpha",
        user_id=str(uuid4()),
        organization_id=org,
    )
    claims = await claims_of(pg_session, response.id)
    check_claims(claims)
    assert claims[3].evidence["matcher_source"]["unit_number"] == "102"

    summary = response.summary.owner_match
    assert summary is not None and summary.version == MATCHER_VERSION
    assert summary.rows == {
        "matched_sale": 3,
        "matched_sale_via_mortgage": 1,
        "lender": 1,
        "no_evidence": 1,
    }
    assert summary.units.model_dump() == {
        "total": 4,
        "confirmed": 3,
        "review": 0,
        "property_only": 0,
        "not_matched": 1,
    }
    assert summary.rows_without_unit == 0

    # the rows endpoint shows the verdicts and filters on them
    async def page(**filters):
        return await owners.get_contact_list(
            pg_session,
            list_id=response.list_id,
            organization_id=org,
            status=None,
            search=None,
            limit=50,
            offset=0,
            **filters,
        )

    everything = await page()
    by_name = {row.contact_name: row for row in everything.contacts}
    assert by_name["Buyer Two"].match_colour == "green"
    assert by_name["Buyer Two"].matched_sale.amount_aed == 1_500_000
    assert by_name["Emirates NBD Bank PJSC"].match_outcome == "lender"
    assert {row.match_colour for row in (await page(match_colour=["green"])).contacts} == {"green"}
    assert (await page(match_colour=["grey"])).total == 2
    lenders = await page(match_outcome=["lender"])
    assert [row.contact_name for row in lenders.contacts] == ["Emirates NBD Bank PJSC"]
    assert (await page(match_colour=["grey"], match_outcome=["lender"])).total == 1


async def test_a_rematch_of_claims_with_no_stored_source_gives_the_same_verdicts(
    pg_session, monkeypatch, property_first_matcher
):
    legacy_stages(monkeypatch)
    warehouse(monkeypatch)
    org = str(uuid4())
    csv = "\n".join([HEADERS, *ROWS]).encode()
    response = await imports._execute_contact_import(
        pg_session,
        upload=UploadFile(file=io.BytesIO(csv), filename="alpha.csv"),
        name="Alpha",
        user_id=str(uuid4()),
        organization_id=org,
    )
    # An import made before the property-first matcher kept no verdict and no matcher source
    # (its original file may be gone, so it cannot be replayed).
    for claim in (await claims_of(pg_session, response.id)).values():
        evidence = dict(claim.evidence)
        stored = evidence.pop("matcher_source")
        assert stored
        evidence.pop("owner_match")
        claim.evidence = evidence
        claim.ownership_status = "unmatched"
    record = await pg_session.get(CrmContactImport, response.id)
    record.summary = {**record.summary, "owner_match": None}
    await pg_session.commit()

    counts = await ownership.rematch_property_contact_claims(
        pg_session, organization_id=org, import_id=response.id, only_unmatched=False
    )
    assert counts["claims"] == 6
    claims = await claims_of(pg_session, response.id)
    check_claims(claims)
    assert claims[4].evidence["matcher_source"]["transaction_price_aed"] == "1500000"
    await pg_session.refresh(record)
    refreshed = record.summary["owner_match"]
    assert refreshed["rows"] == {
        "matched_sale": 3,
        "matched_sale_via_mortgage": 1,
        "lender": 1,
        "no_evidence": 1,
    }
    assert refreshed["units"]["confirmed"] == 3
