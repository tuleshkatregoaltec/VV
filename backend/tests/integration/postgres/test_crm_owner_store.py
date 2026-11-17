"""The stored assessment answers every Owners read exactly as the whole snapshot did.

A tenant is assessed once, in chunks, and written to PostgreSQL; the reads then use the
narrowest key they have. Each read is compared here with the original whole-snapshot read
(`tests/support/legacy_owner_reads.py`) over the same committed claims.
"""

import itertools
import json
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import legacy_owner_reads as legacy
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.crm import imports, owner_assessment, owner_history, owner_repository, owner_store, owners
from app.crm import workspaces as workspace_service
from app.crm.import_models import (
    CrmContactImport,
    CrmContactList,
    CrmOwnerWorkspace,
    CrmPropertyContactClaim,
)
from app.crm.source_audit import source_audit_for_row

TODAY = date.today()
REGISTRY = {
    ("aspecttower", "601"): [date(2019, 3, 1), 900_000],
    ("aspecttower", "602"): [date(2020, 1, 1), 1_000_000],
    ("aspecttower", "603"): [date(2020, 6, 1), 1_100_000],
    ("aspecttower", "604"): [date(2021, 2, 1), 1_200_000],
    ("skyheights", "101"): [date(2022, 5, 1), 2_000_000],
    ("skyheights", "102"): [date(2022, 7, 1), 2_100_000],
    ("skyheights", "103"): [date(2018, 1, 1), 800_000],
}


@pytest.fixture
def evidence(monkeypatch):
    """Registry sales for the synthetic units, and a stable evidence revision."""
    state = {"revision": "evidence-1"}

    async def fresh_sales(candidates):
        result = {}
        for _, candidate in candidates:
            building = candidate.property_key.split("|")[0]
            sale = REGISTRY.get((building, candidate.unit_number))
            result[candidate.property_key] = (
                [
                    {
                        "sale_key": f"{building}-{candidate.unit_number}",
                        "transaction_date": sale[0],
                        "sale_amount_aed": sale[1],
                        "area_name": "Business Bay",
                        "building_name": candidate.building_name,
                        "project_name": candidate.project_name,
                        "unit_number": candidate.unit_number,
                        "property_type": "Apartment",
                    }
                ]
                if sale
                else []
            )
        return result

    async def warehouse_revision():
        return state["revision"]

    monkeypatch.setattr(owner_assessment, "_fresh_sales", fresh_sales)
    monkeypatch.setattr(owner_assessment, "_warehouse_revision", warehouse_revision)
    monkeypatch.setattr(owner_store, "CHUNK_CLAIMS", 7)
    monkeypatch.setattr(owner_store.profiles, "OWNER_SLICE", 4)
    return state


async def _import(db, org, name):
    now = datetime.now(timezone.utc)
    user = str(uuid4())
    record = CrmContactImport(
        organization_id=org,
        created_by_user_id=user,
        name=name,
        original_filename=f"{name}.xlsx",
        sha256=uuid4().hex,
        size_bytes=100,
        status="completed",
        mapping={},
        created_at=now,
    )
    db.add(record)
    await db.flush()
    contact_list = CrmContactList(
        organization_id=org,
        created_by_user_id=user,
        source_import_id=record.id,
        name=name,
        created_at=now,
        updated_at=now,
    )
    db.add(contact_list)
    await db.flush()
    return record, contact_list


def _claim(record, contact_list, number, building, unit, name, **changes):
    now = datetime.now(timezone.utc)
    sky = building == "Sky Heights"
    return CrmPropertyContactClaim(
        **{
            "organization_id": record.organization_id,
            "import_id": record.id,
            "list_id": contact_list.id,
            "source_sheet": "Owners",
            "source_row_number": number,
            "row_fingerprint": uuid4().hex,
            "owner_key": f"key-{name.lower().replace(' ', '-')}",
            "property_key": f"{building.lower().replace(' ', '')}|{unit}",
            "contact_name": name,
            "phone_primary": f"+9715{abs(hash(name)) % 10_000_000:07d}",
            "area_name": "Business Bay",
            "building_name": building,
            "project_name": "Sky Heights" if sky else "Executive Towers",
            "unit_number": unit,
            "party_role": "Buyer",
            "procedure_type": "Sell",
            "property_type": "Apartment",
            "ownership_status": "verified_current_owner",
            "confidence_score": 90,
            "match_reason": "Saved",
            "transaction_date": REGISTRY.get((building.lower().replace(" ", ""), unit), [None])[0],
            "transaction_price_aed": REGISTRY.get(
                (building.lower().replace(" ", ""), unit), [None, None]
            )[1],
            "created_at": now,
            "updated_at": now,
            "evidence": {},
            **changes,
        }
    )


@pytest.fixture
async def tenant(pg_session, evidence):
    """Two imports, owners with several units, a competing seller, a shared persisted key."""
    org = str(uuid4())
    first, first_list = await _import(pg_session, org, "First file")
    second, second_list = await _import(pg_session, org, "Second file")
    lease = TODAY + timedelta(days=45)
    claims = [
        # Alice holds two units, one of them leased
        _claim(first, first_list, 1, "Aspect Tower", "601", "Alice Example"),
        _claim(
            first,
            first_list,
            2,
            "Aspect Tower",
            "602",
            "Alice Example",
            lead_id="lead-602",
            unit_candidate_key="unit-602",
            lease_end=lease,
            annual_rent_aed=90_000,
        ),
        # Bob bought 602 earlier on the other file: a competing, later registry sale decides
        _claim(
            second,
            second_list,
            1,
            "Aspect Tower",
            "602",
            "Bob Example",
            transaction_date=date(2018, 1, 1),
            transaction_price_aed=700_000,
        ),
        # Carol sold 603 and Dan bought it
        _claim(first, first_list, 3, "Aspect Tower", "603", "Carol Seller", party_role="Seller"),
        _claim(second, second_list, 2, "Aspect Tower", "603", "Dan Buyer"),
        # Erin holds three units
        _claim(second, second_list, 3, "Sky Heights", "101", "Erin Portfolio"),
        _claim(
            second,
            second_list,
            4,
            "Sky Heights",
            "102",
            "Erin Portfolio",
            lead_id="lead-102",
            unit_candidate_key="unit-102",
            lease_end=TODAY + timedelta(days=200),
            annual_rent_aed=150_000,
        ),
        _claim(first, first_list, 4, "Sky Heights", "103", "Erin Portfolio"),
        # Two different people share one persisted owner key
        _claim(first, first_list, 5, "Aspect Tower", "604", "Frank One", owner_key="shared-key"),
        _claim(second, second_list, 5, "Sky Heights", "103", "Gina Two", owner_key="shared-key"),
        # A unit the registry does not know, and a row with no usable property identity
        _claim(first, first_list, 6, "Aspect Tower", "699", "Hana Unknown"),
        _claim(
            first,
            first_list,
            7,
            "Aspect Tower",
            "604",
            "Ivan Invalid",
            property_key="not-a-key",
        ),
    ]
    pg_session.add_all(claims)
    await pg_session.commit()
    return {"org": org, "imports": [first.id, second.id], "lists": [first_list.id, second_list.id]}


def _plain(value):
    """JSON-comparable, without the build instant."""
    data = json.loads(
        json.dumps(
            value.model_dump(mode="json") if hasattr(value, "model_dump") else value, default=str
        )
    )

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in {"checked_at", "cached_at"}}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return strip(data)


async def _legacy_snapshot(db, org):
    snapshot = await owner_assessment.get_owner_assessment(db, organization_id=org)
    # The whole snapshot lists rows in whatever order PostgreSQL returned them; the stored
    # assessment pins claim order (source-audit rows last), so give the oracle the same order.
    snapshot.rows.sort(key=lambda row: (bool(source_audit_for_row(row)), row["id"]))
    legacy.SNAPSHOT = snapshot
    return snapshot


async def test_stored_rows_are_the_whole_snapshot_rows(pg_session, tenant):
    org = tenant["org"]
    snapshot = await _legacy_snapshot(pg_session, org)
    store = await owner_store.open_store(pg_session, org)
    stored = {row["id"]: row for row in await store.rows("TRUE")}
    expected = {row["id"]: row for row in snapshot.rows}
    assert stored.keys() == expected.keys()
    for claim_id, row in expected.items():
        assert _plain(stored[claim_id]) == _plain(row)
    assert _plain(store.state.summary) == _plain(snapshot.summary)


async def test_properties_split_across_chunks_are_assessed_together(
    pg_session, tenant, monkeypatch
):
    """A property whose claims fell in two chunks is assessed again whole."""
    org = tenant["org"]
    assessed_together = []
    original = owner_assessment._build

    async def spy(db, organization_id, **kwargs):
        rows = kwargs.get("rows") or []
        assessed_together.append({row["id"] for row in rows})
        return await original(db, organization_id, **kwargs)

    monkeypatch.setattr(owner_assessment, "_build", spy)
    monkeypatch.setattr(owner_store, "CHUNK_CLAIMS", 3)
    store = await owner_store.open_store(pg_session, org)
    by_property: dict[str, set[int]] = {}
    for row in await store.rows("TRUE"):
        by_property.setdefault(row["property_key"], set()).add(row["id"])
    for key, members in by_property.items():
        if len(members) > 1:
            assert any(members <= batch for batch in assessed_together), key


async def test_a_changed_source_revision_is_rebuilt(pg_session, tenant, evidence):
    org = tenant["org"]
    first = await owner_store.open_store(pg_session, org)
    again = await owner_store.open_store(pg_session, org)
    assert again.state.generation == first.state.generation
    await pg_session.execute(
        text(
            "UPDATE crm_property_contact_claims SET confidence_score = 91 WHERE organization_id = :o"
        ),
        {"o": org},
    )
    await pg_session.commit()
    rebuilt = await owner_store.open_store(pg_session, org)
    assert rebuilt.state.generation > first.state.generation
    remaining = (
        await pg_session.exec(
            text(
                "SELECT DISTINCT generation FROM crm_owner_assessed_claims WHERE organization_id = :o"
            ),
            params={"o": org},
        )
    ).all()
    assert [row[0] for row in remaining] == [rebuilt.state.generation]
    evidence["revision"] = "evidence-2"
    assert (
        await owner_store.open_store(pg_session, org)
    ).state.generation > rebuilt.state.generation


async def test_a_busy_build_keeps_serving_the_previous_assessment(pg_session, tenant, monkeypatch):
    org = tenant["org"]
    first = await owner_store.open_store(pg_session, org)
    await pg_session.execute(
        text(
            "UPDATE crm_property_contact_claims SET confidence_score = 92 WHERE organization_id = :o"
        ),
        {"o": org},
    )
    await pg_session.commit()

    async def slow(engine, organization_id):
        import asyncio

        await asyncio.sleep(5)

    monkeypatch.setattr(owner_store, "STALE_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(owner_store, "rebuild", slow)
    served = await owner_store.open_store(pg_session, org)
    assert served.state.generation == first.state.generation
    owner_store._BUILDS[org].cancel()


def _registry_arguments(**changes):
    return (
        dict(
            list_id=None,
            scope="all",
            status=None,
            search=None,
            lease_window=None,
            portfolio_only=False,
            min_rent_aed=None,
            max_rent_aed=None,
            min_value_aed=None,
            max_value_aed=None,
            limit=3,
            offset=0,
            min_properties=None,
            next_event_days=None,
            transaction_match_status=None,
        )
        | changes
    )


REGISTRY_CASES = [
    {},
    {"offset": 3},
    {"offset": 99},
    {"scope": "prior_owners"},
    {"scope": "needs_review"},
    {"scope": "current_owners"},
    {"scope": "rental_ready"},
    {"scope": "registry"},
    {"min_properties": 2},
    {"min_properties": 3},
    {"next_event_days": 90},
    {"next_event_days": 365, "scope": "current_owners"},
    {"portfolio_only": True},
    {"search": "erin"},
    {"search": "sky"},
    {"search": "  "},
    {"search": "+9715"},
    {"status": "former_owner"},
    {"status": "insufficient_property_data"},
    {"lease_window": "expiring_60"},
    {"lease_window": "expiring_90"},
    {"lease_window": "expired"},
    {"min_rent_aed": 80_000, "max_rent_aed": 100_000},
    {"min_value_aed": 1_000_000},
    {"max_value_aed": 1_000_000, "scope": "current_owners"},
    {"transaction_match_status": "matched"},
    {"scope": "prior_owners", "search": "carol", "limit": 10},
    {"scope": "needs_review", "search": "ivan"},
]


@pytest.mark.parametrize("case", REGISTRY_CASES, ids=lambda case: json.dumps(case, sort_keys=True))
@pytest.mark.parametrize("list_choice", [None, 0, 1])
async def test_registry_matches_the_whole_snapshot(pg_session, tenant, case, list_choice):
    org = tenant["org"]
    await _legacy_snapshot(pg_session, org)
    list_id = None if list_choice is None else tenant["lists"][list_choice]
    arguments = _registry_arguments(**case, **({"list_id": list_id} if list_id else {}))
    expected = await legacy.get_owner_registry(pg_session, organization_id=org, **arguments)
    actual = await owners.get_owner_registry(pg_session, organization_id=org, **arguments)
    assert _plain(actual) == _plain(expected)


async def test_every_page_of_the_registry_matches(pg_session, tenant):
    org = tenant["org"]
    await _legacy_snapshot(pg_session, org)
    for scope, offset in itertools.product(
        ["all", "prior_owners", "needs_review"], range(0, 12, 2)
    ):
        arguments = _registry_arguments(scope=scope, offset=offset, limit=2)
        assert _plain(
            await owners.get_owner_registry(pg_session, organization_id=org, **arguments)
        ) == _plain(await legacy.get_owner_registry(pg_session, organization_id=org, **arguments))


async def _outcome(awaitable):
    try:
        return _plain(await awaitable)
    except HTTPException as error:
        return (error.status_code, error.detail)


async def _legacy_profile(snapshot, key):
    canonical = {
        row["canonical_owner_key"]
        for row in snapshot.rows
        if row["owner_key"] == key or row["canonical_owner_key"] == key
    }
    if not canonical:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    if len(canonical) != 1:
        raise HTTPException(
            status_code=409,
            detail="This legacy owner key contains multiple contact identities; select an owner from the registry to review its evidence.",
        )
    profiles = await legacy._profiles_for_snapshot(snapshot)
    selected = next(iter(canonical))
    if selected not in profiles:
        raise HTTPException(status_code=404, detail="No reviewed owner candidate for this party")
    return profiles[selected].model_copy(deep=True)


async def test_owner_profile_and_history_match(pg_session, tenant, monkeypatch):
    org = tenant["org"]
    snapshot = await _legacy_snapshot(pg_session, org)

    async def no_registry(profile):
        return profile

    monkeypatch.setattr(owners, "_enrich_owner_profile_registry", no_registry)
    keys = {row["owner_key"] for row in snapshot.rows} | {
        row["canonical_owner_key"] for row in snapshot.rows
    }
    saw_conflict = False
    for key in sorted(keys) + ["unknown-owner"]:
        for extra in ({"limit": 2, "offset": 1}, {"import_id": tenant["imports"][1]}):
            actual = await _outcome(
                owner_history.get_owner_history(
                    pg_session, organization_id=org, owner_key=key, **extra
                )
            )
            expected = await _outcome(
                legacy.get_owner_history(pg_session, organization_id=org, owner_key=key, **extra)
            )
            assert actual == expected, (key, extra)
        actual = await _outcome(
            owners.get_owner_profile(pg_session, organization_id=org, owner_key=key)
        )
        expected = await _outcome(_awaitable(_legacy_profile(snapshot, key)))
        assert actual == expected, key
        saw_conflict |= isinstance(actual, tuple) and actual[0] == 409
    assert saw_conflict, "the shared persisted key should be ambiguous"


async def _awaitable(coroutine):
    return await coroutine


async def test_list_reads_match(pg_session, tenant):
    org = tenant["org"]
    await _legacy_snapshot(pg_session, org)
    assert _plain(await owners.list_contact_lists(pg_session, organization_id=org)) == _plain(
        await legacy.list_contact_lists(pg_session, organization_id=org)
    )
    cases = [
        {},
        {"offset": 2, "limit": 2},
        {"search": "erin"},
        {"search": "  "},
        {"status": "verified_current_owner"},
        {"status": "former_owner"},
        {"match_colour": ["green", "amber"]},
        {"match_outcome": ["lender"]},
    ]
    for list_id in tenant["lists"]:
        for case in cases:
            arguments = (
                dict(
                    status=None,
                    search=None,
                    limit=100,
                    offset=0,
                    match_colour=None,
                    match_outcome=None,
                )
                | case
            )
            assert _plain(
                await owners.get_contact_list(
                    pg_session, list_id=list_id, organization_id=org, **arguments
                )
            ) == _plain(
                await legacy.get_contact_list(
                    pg_session, list_id=list_id, organization_id=org, **arguments
                )
            ), (list_id, case)


async def test_import_properties_and_summaries_match(pg_session, tenant):
    org = tenant["org"]
    await _legacy_snapshot(pg_session, org)
    for import_id in tenant["imports"]:
        for case in ({}, {"search": "erin"}, {"search": "aspect"}, {"offset": 1, "limit": 2}):
            arguments = dict(search=None, limit=100, offset=0) | case
            assert _plain(
                await imports.list_import_properties(
                    pg_session, import_id=import_id, organization_id=org, **arguments
                )
            ) == _plain(
                await legacy.list_import_properties(
                    pg_session, import_id=import_id, organization_id=org, **arguments
                )
            ), (import_id, case)
        assert _plain(
            await owner_history.get_owner_history_summary(
                pg_session, organization_id=org, import_id=import_id
            )
        ) == _plain(
            await legacy.get_owner_history_summary(
                pg_session, organization_id=org, import_id=import_id
            )
        )
    assert _plain(
        await owner_history.get_owner_history_summary(pg_session, organization_id=org)
    ) == _plain(await legacy.get_owner_history_summary(pg_session, organization_id=org))


async def test_lead_contacts_and_workspaces_match(pg_session, tenant):
    org, user = tenant["org"], str(uuid4())
    await _legacy_snapshot(pg_session, org)
    for lead in ("lead-602", "lead-102", "no-such-lead"):
        assert _plain(
            await owners.list_lead_imported_contacts(pg_session, lead_id=lead, organization_id=org)
        ) == _plain(
            await legacy.list_lead_imported_contacts(pg_session, lead_id=lead, organization_id=org)
        )
    now = datetime.now(timezone.utc)
    rows = (
        await pg_session.exec(
            text(
                "SELECT DISTINCT owner_key FROM crm_property_contact_claims WHERE organization_id = :o"
            ),
            params={"o": org},
        )
    ).all()
    for (key,) in rows:
        pg_session.add(
            CrmOwnerWorkspace(
                user_id=user,
                organization_id=org,
                owner_key=key,
                pipeline_status="contact_ready",
                highlight_color="green",
                tags=[],
                created_at=now,
                updated_at=now,
            )
        )
    await pg_session.commit()
    assert _plain(
        await workspace_service.list_owner_workspaces(pg_session, user_id=user, organization_id=org)
    ) == _plain(await legacy.list_owner_workspaces(pg_session, user_id=user, organization_id=org))


async def test_claims_chunking_reads_each_claim_once(pg_session, tenant):
    org = tenant["org"]
    ids = [
        row.id
        for row in (
            await pg_session.exec(
                text("SELECT id FROM crm_property_contact_claims WHERE organization_id = :o"),
                params={"o": org},
            )
        ).all()
    ]
    rows = await owner_repository.list_owner_history_rows(
        pg_session, organization_id=org, claim_ids=ids[:5]
    )
    assert {row["id"] for row in rows} == set(ids[:5])


async def test_an_unavailable_registry_is_never_published_as_confirmed_ownership(
    pg_session, tenant, evidence, monkeypatch
):
    """Without registry evidence the tenant is assessed as unconfirmed, and only briefly."""
    org = tenant["org"]
    available = await owner_store.open_store(pg_session, org)
    assert available.state.warehouse_status == "available"

    async def unavailable():
        return None

    monkeypatch.setattr(owner_assessment, "_warehouse_revision", unavailable)
    degraded = await owner_store.open_store(pg_session, org)
    assert degraded.state.warehouse_status == "unavailable"
    assert degraded.state.generation > available.state.generation
    statuses = {row["assessed_status"] for row in await degraded.rows("TRUE")}
    assert not statuses & {"verified_current_owner", "former_owner"}
    # while it is fresh it is reused; once it is stale a rebuild is attempted again
    assert (await owner_store.open_store(pg_session, org)).state.generation == (
        degraded.state.generation
    )
    monkeypatch.setattr(owner_store, "UNAVAILABLE_LIFETIME_SECONDS", -1)
    assert (await owner_store.open_store(pg_session, org)).state.generation > (
        degraded.state.generation
    )


async def test_claims_on_one_unit_number_are_assessed_in_the_same_chunk(
    pg_session, tenant, monkeypatch
):
    """A project-level claim finds sales that other claims' unit pairs brought in."""
    org = tenant["org"]
    monkeypatch.setattr(owner_store, "CHUNK_CLAIMS", 2)
    chunks = await owner_store._claim_chunks(pg_session.bind, org)
    unit_of = {
        row[0]: owner_store._unit_group(row[1])
        for row in (
            await pg_session.exec(
                text(
                    "SELECT id, unit_number FROM crm_property_contact_claims WHERE organization_id = :o"
                ),
                params={"o": org},
            )
        ).all()
    }
    homes = {}
    for index, chunk in enumerate(chunks):
        for claim_id in chunk:
            assert homes.setdefault(unit_of[claim_id], index) == index, unit_of[claim_id]
    assert len(chunks) > 1
    assert sorted(claim for chunk in chunks for claim in chunk) == sorted(unit_of)


async def test_a_lease_refresh_changes_only_lease_fields_and_reaches_the_published_store(
    pg_session, tenant, monkeypatch
):
    """The post-load refresh: claims get today's lease, owner work is untouched, and the
    republished assessment serves the new lease without a request building it."""
    from unittest.mock import AsyncMock

    from app.crm import ownership

    org = tenant["org"]
    first = await owner_store.publish_if_stale(pg_session.bind, org)
    lease_fields = ("lead_id", "unit_candidate_key", "lease_end", "annual_rent_aed", "updated_at")
    snapshot = text(
        "SELECT id, to_jsonb(c) - CAST(:fields AS text[]) AS other, lead_id, lease_end, "
        "annual_rent_aed FROM crm_property_contact_claims c WHERE organization_id = :o ORDER BY id"
    )
    params = {"o": org, "fields": list(lease_fields)}
    before = (await pg_session.execute(snapshot, params)).mappings().all()
    new_end = TODAY + timedelta(days=45)
    monkeypatch.setattr(
        ownership,
        "_rental_evidence_for_units",
        AsyncMock(
            return_value={
                "aspecttower|601": {
                    "event_key": "lead-601",
                    "unit_candidate_key": "unit-601",
                    "lease_end": new_end,
                    "annual_rent_aed": 120_000,
                    "area_name": "Business Bay",
                    "project_name": "Executive Towers",
                }
            }
        ),
    )
    result = await ownership.refresh_property_contact_rentals(pg_session, organization_id=org)
    assert result["added_hits"] >= 1 and result["removed_hits"] >= 1
    after = (await pg_session.execute(snapshot, params)).mappings().all()
    assert [row["other"] for row in after] == [row["other"] for row in before]
    by_id = {row["id"]: row for row in after}
    leased = [row for row in before if row["lead_id"] == "lead-602"]
    assert leased and all(by_id[row["id"]]["lead_id"] is None for row in leased)
    linked = [row for row in after if row["lead_id"] == "lead-601"]
    assert linked and all(
        (row["lease_end"], row["annual_rent_aed"]) == (new_end, 120_000) for row in linked
    )

    published = await owner_store.publish_if_stale(pg_session.bind, org)
    assert published.generation > first.generation
    served = await owner_store.open_store(pg_session, org)
    assert served.state.generation == published.generation
    assessed = (
        await pg_session.exec(
            text(
                "SELECT DISTINCT lead_id FROM crm_owner_assessed_claims "
                "WHERE organization_id = :o AND generation = :g AND lead_id IS NOT NULL"
            ),
            params={"o": org, "g": published.generation},
        )
    ).all()
    assert [row[0] for row in assessed] == ["lead-601"]


@pytest.mark.parametrize("list_choice", [None, 0])
async def test_folder_counts_reconcile_with_all(pg_session, tenant, list_choice):
    # Live: all 178,793 vs registry 98,808 + prior 55,134; folders overlap and developer-side
    # sellers are in no folder. The summary now names both, so the numbers add up.
    org = tenant["org"]
    list_id = None if list_choice is None else tenant["lists"][list_choice]
    page = await owners.get_owner_registry(
        pg_session,
        organization_id=org,
        **_registry_arguments(**({"list_id": list_id} if list_id else {})),
    )
    s = page.summary
    assert page.total == (
        s.rental_owner_profiles
        + s.registry_owner_profiles
        + s.prior_owner_profiles
        - s.folder_overlap
        + s.unfiled_profiles
    )


async def test_valuation_rebuilds_current_projection_and_filters_by_estimate(pg_session, tenant):
    """A new estimate must reach stored profiles and filters without rewriting the old sale."""
    from sqlmodel import select

    org = tenant["org"]
    before = await owner_store.open_store(pg_session, org)
    claim = (
        await pg_session.exec(
            select(CrmPropertyContactClaim).where(
                CrmPropertyContactClaim.organization_id == org,
                CrmPropertyContactClaim.contact_name == "Alice Example",
                CrmPropertyContactClaim.unit_number == "601",
            )
        )
    ).one()
    claim.estimated_value_aed = 2_600_000
    claim.estimated_value_low_aed = 2_500_000
    claim.estimated_value_high_aed = 2_800_000
    claim.valuation = {"confidence": "high", "valued_at": "2026-11-05", "status": "valued"}
    await pg_session.commit()
    await owner_store.rebuild(pg_session.bind, org)
    refreshed = await owner_store.open_store(pg_session, org)
    assert refreshed.state.generation != before.state.generation
    result = await owners.get_owner_registry(
        pg_session,
        organization_id=org,
        **_registry_arguments(
            search="Alice",
            min_value_aed=2_500_000,
            max_value_aed=2_800_000,
        ),
    )
    assert result.total == 1
    prop = next(p for p in result.owners[0].properties if p.unit_number == "601")
    assert (prop.estimated_value_aed, prop.valuation_confidence, prop.valued_at) == (
        2_600_000,
        "high",
        date(2026, 11, 5),
    )
    assert prop.latest_sale_price_aed == 900_000
    values = (
        await pg_session.exec(
            text(
                "SELECT sale_price_aed, estimated_value_aed FROM crm_owner_registry_properties "
                "WHERE organization_id=:org AND generation=:gen AND estimated_value_aed IS NOT NULL"
            ),
            params={"org": org, "gen": refreshed.state.generation},
        )
    ).all()
    assert values and all(tuple(row) == (900_000, 2_600_000) for row in values)

    claim.estimated_value_aed = None
    claim.estimated_value_low_aed = None
    claim.estimated_value_high_aed = None
    claim.valuation = {"status": "no_registry_match"}
    await pg_session.commit()
    await owner_store.rebuild(pg_session.bind, org)
    cleared = await owners.get_owner_registry(
        pg_session,
        organization_id=org,
        **_registry_arguments(
            search="Alice",
            min_value_aed=2_500_000,
        ),
    )
    assert cleared.total == 0
    fallback = await owners.get_owner_registry(
        pg_session,
        organization_id=org,
        **_registry_arguments(
            search="Alice",
            min_value_aed=800_000,
            max_value_aed=950_000,
        ),
    )
    assert fallback.total == 1


async def test_maintenance_valuation_uses_assessment_without_rewriting_import(
    pg_session, tenant, monkeypatch
):
    from sqlmodel import select

    from app.crm import valuation_service

    org = tenant["org"]
    former = (
        await pg_session.exec(
            select(CrmPropertyContactClaim).where(
                CrmPropertyContactClaim.organization_id == org,
                CrmPropertyContactClaim.contact_name == "Carol Seller",
            )
        )
    ).one()
    assert former.ownership_status == "verified_current_owner"  # stale import assertion
    former.estimated_value_aed = 9_000_000
    await pg_session.commit()

    async def value_current(claims, valued_at, summary):
        assert former.id not in {claim.id for claim in claims}
        for claim in claims:
            claim.estimated_value_aed = 2_600_000
            claim.estimated_value_low_aed = 2_500_000
            claim.estimated_value_high_aed = 2_800_000
            claim.valuation = {"confidence": "high", "valued_at": valued_at.isoformat()}
            summary.valued += 1

    monkeypatch.setattr(valuation_service, "_value_chunk", value_current)
    result = await valuation_service.value_owner_claims(pg_session, organization_id=org)
    assert result.valued > 0
    await pg_session.refresh(former)
    assert former.estimated_value_aed is None
    assert former.valuation["status"] == "not_current_owner"
    assert former.ownership_status == "verified_current_owner"
