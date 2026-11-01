"""Production CRM routes + real PG, with two mocked authenticated identities.

GoTrue and subscription verification are outside this boundary. Domain operations,
repositories, source revisions, actor dependency, and SQL triggers execute for real.
"""

import gzip
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import AuthContext, require_active_subscription, require_auth
from app.crm import import_drop_log, inbound, matching
from app.crm.import_models import (
    CrmContactImport,
    CrmContactList,
    CrmOwnerNote,
    CrmOwnerWorkspace,
    CrmPropertyContactClaim,
)
from app.crm.inbound_models import CrmInboundEnquiry, InboundEnquiryCreate
from app.crm.models import CrmLeadNote, CrmLeadWorkspace
from app.crm.router import router
from app.organization.models import Organization, OrganizationMembership
from app.postgres import get_db_session
from app.postgres.actor_context import install_actor_context, transaction_actor


async def seed_tenant(db, suffix):
    now = datetime.now(timezone.utc)
    org, user = str(uuid4()), str(uuid4())
    name, note = f"PRIVATE CONTACT {suffix}", f"PRIVATE NOTE {suffix}"
    record = CrmContactImport(
        organization_id=org,
        created_by_user_id=user,
        name=f"PRIVATE IMPORT {suffix}",
        original_filename=f"private-{suffix}.csv",
        sha256=uuid4().hex,
        size_bytes=1,
        status="completed",
        mapping={"resolver_version": "test", "mode": "source_only", "sheets": []},
        summary={"dropped_by_reason": {"no_name": 1}},
        created_at=now,
    )
    db.add(record)
    await db.flush()
    contact_list = CrmContactList(
        organization_id=org,
        created_by_user_id=user,
        source_import_id=record.id,
        name=f"PRIVATE LIST {suffix}",
        created_at=now,
        updated_at=now,
    )
    db.add(contact_list)
    await db.flush()
    # Identical lookup keys/phone deliberately collide across tenant cache namespaces.
    claim = CrmPropertyContactClaim(
        organization_id=org,
        import_id=record.id,
        list_id=contact_list.id,
        source_sheet="Owners",
        source_row_number=1,
        row_fingerprint="one",
        owner_key="shared-owner",
        property_key="shared-property",
        contact_name=name,
        phone_primary="+971501234567",
        ownership_status="unmatched",
        match_reason="Synthetic",
        evidence={
            "source_audit": {
                "mode": "source_only",
                "canonical_owner_key": "shared-owner",
                "owner_candidate": True,
                "decision_basis": "Synthetic reviewed fixture",
                "reference_id": "same-reference",
                "source_key": ["unit", "Synthetic", "1"],
                "disposition": "owner_candidate",
            }
        },
        created_at=now,
        updated_at=now,
    )
    owner_workspace = CrmOwnerWorkspace(
        organization_id=org,
        user_id=user,
        owner_key="shared-owner",
        created_at=now,
        updated_at=now,
    )
    lead_workspace = CrmLeadWorkspace(
        organization_id=org,
        user_id=user,
        lead_id="shared-lead",
        unit_candidate_key="shared-candidate",
        owner_name=name,
        created_at=now,
        updated_at=now,
    )
    db.add_all([claim, owner_workspace, lead_workspace])
    await db.flush()
    db.add_all(
        [
            CrmOwnerNote(
                workspace_id=owner_workspace.id,
                organization_id=org,
                user_id=user,
                body=note,
                created_at=now,
                updated_at=now,
            ),
            CrmLeadNote(
                workspace_id=lead_workspace.id,
                organization_id=org,
                user_id=user,
                body=note,
                created_at=now,
                updated_at=now,
            ),
        ]
    )
    await db.commit()
    with transaction_actor(actor_id=user, organization_id=org, request_id=uuid4().hex):
        enquiry_response = await inbound.create_inbound_enquiry(
            db, payload=InboundEnquiryCreate(full_name=name), user_id=user, organization_id=org
        )
        enquiry = await db.get(CrmInboundEnquiry, enquiry_response.id)
        match = await matching._upsert_match(
            db,
            enquiry=enquiry,
            target_type="owner",
            target_key="shared-owner",
            score=75,
            title=name,
            subtitle="Synthetic",
            reasons=[],
            breakdown={},
            snapshot={"private": name},
        )
        await db.commit()
    note_id = (
        await db.exec(
            text("SELECT id FROM crm_lead_notes WHERE organization_id=:org"), params={"org": org}
        )
    ).scalar_one()
    result = SimpleNamespace(
        org=org,
        user=user,
        name=name,
        note=note,
        source_id=record.id,
        list_id=contact_list.id,
        enquiry_id=enquiry_response.id,
        match_id=match.id,
        note_id=note_id,
        active=True,
    )
    await db.rollback()
    return result


@pytest.fixture
async def tenant_http(pg_session, monkeypatch):
    install_actor_context(pg_session.bind)
    tenants = {key: await seed_tenant(pg_session, key) for key in ("A", "B")}
    app = FastAPI()
    app.include_router(router)

    async def authenticated(request: Request):
        tenant = tenants[request.headers["x-test-identity"]]
        if not tenant.active:
            raise HTTPException(status_code=403, detail="Membership removed")
        return AuthContext(
            user=SimpleNamespace(id=tenant.user),
            organization=SimpleNamespace(id=tenant.org, subscription_status="active"),
            membership=SimpleNamespace(
                user_id=tenant.user, organization_id=tenant.org, role="member"
            ),
            subscription=None,
        )

    async def database():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[require_active_subscription] = authenticated
    app.dependency_overrides[get_db_session] = database
    objects = {}
    for tenant in tenants.values():
        key = import_drop_log.drop_log_key(tenant.org, tenant.source_id)
        objects[key] = gzip.compress(
            json.dumps(
                [
                    {
                        "sheet": "Owners",
                        "row": 2,
                        "reason": "no_name",
                        "name": tenant.name,
                        "building": "Synthetic",
                        "unit": "",
                        "date": "",
                        "price": "",
                        "role": "",
                        "procedure": "",
                    }
                ]
            ).encode()
        )
    storage = SimpleNamespace(
        download=AsyncMock(side_effect=lambda key: objects[key]), delete_many=AsyncMock()
    )
    monkeypatch.setattr(import_drop_log, "_storage", lambda: storage)
    monkeypatch.setattr(matching, "get_inventory_freshness", AsyncMock(return_value=(None, False)))
    monkeypatch.setattr(matching, "get_catalog_freshness", AsyncMock(return_value=None))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, tenants, storage


async def test_two_org_private_reads_remain_isolated_after_both_caches_are_warm(tenant_http):
    client, tenants, storage = tenant_http
    # Return to A and B after warming the other org's in-process/serialized caches.
    for identity in ("A", "B", "A", "B"):
        own = tenants[identity]
        other = tenants["B" if identity == "A" else "A"]
        headers = {"x-test-identity": identity}
        for path in (
            "/contact-imports",
            "/contact-lists",
            "/owner-registry?scope=all",
            "/owners/shared-owner",
            "/owners/shared-owner/history",
            "/owner-history/summary",
            "/owner-workspaces",
            "/workspaces",
            "/inbound/enquiries",
            f"/inbound/enquiries/{own.enquiry_id}",
            f"/inbound/enquiries/{own.enquiry_id}/matches",
            f"/contact-imports/{own.source_id}/properties",
            f"/contact-imports/{own.source_id}/dropped-rows",
        ):
            response = await client.get("/api/v1/crm" + path, headers=headers)
            assert response.status_code == 200, (path, response.text)
            assert other.name not in response.text, path
            assert other.note not in response.text, path
            if path == "/owners/shared-owner":
                assert response.json()["contact_name"] == own.name
            if path == "/owners/shared-owner/history":
                assert [event["import_id"] for event in response.json()["events"]] == [
                    own.source_id
                ]
            if path == "/owner-workspaces":
                assert response.json()[0]["last_note"] == own.note
        before = storage.download.await_count
        for path in (
            f"/contact-imports/{other.source_id}/dropped-rows",
            f"/contact-imports/{other.source_id}/properties",
            f"/contact-imports/{other.source_id}/owner-summary",
            f"/contact-lists/{other.list_id}",
            f"/owners/shared-owner/history?import_id={other.source_id}",
            f"/inbound/enquiries/{other.enquiry_id}",
            f"/inbound/enquiries/{other.enquiry_id}/matches",
        ):
            response = await client.get("/api/v1/crm" + path, headers=headers)
            assert response.status_code == 404, (path, response.text)
            assert other.name not in response.text
        assert storage.download.await_count == before  # foreign object denied before storage


async def test_foreign_mutations_are_denied_and_own_commits_have_http_actor(
    tenant_http, pg_session
):
    client, tenants, _ = tenant_http
    for identity in ("A", "B"):
        own, other = tenants[identity], tenants["B" if identity == "A" else "A"]
        headers = {"x-test-identity": identity}
        for method, path, payload in (
            ("PATCH", f"/contact-imports/{other.source_id}", {"name": "CROSS ORG"}),
            ("DELETE", f"/contact-imports/{other.source_id}", None),
            ("PATCH", f"/inbound/enquiries/{other.enquiry_id}", {"status": "contacted"}),
            ("POST", f"/inbound/enquiries/{other.enquiry_id}/notes", {"body": "CROSS ORG"}),
            ("PATCH", f"/inbound/matches/{other.match_id}", {"state": "saved"}),
            ("DELETE", f"/notes/{other.note_id}", None),
        ):
            response = await client.request(
                method, "/api/v1/crm" + path, json=payload, headers=headers
            )
            assert response.status_code == 404, (path, response.text)
        response = await client.patch(
            f"/api/v1/crm/contact-imports/{own.source_id}",
            json={"name": f"RENAMED {identity}"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        # Bulk workspace + note writes exercise service commits and subsequent reads.
        response = await client.patch(
            "/api/v1/crm/owner-workspaces/bulk",
            json={"owner_keys": ["shared-owner"], "pipeline_status": "contacted", "note": own.note},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        rows = (
            (
                await pg_session.exec(
                    text("""
            SELECT actor_id, request_id, resource FROM crm_mutation_audit
            WHERE organization_id=:org AND action='UPDATE'
        """),
                    params={"org": own.org},
                )
            )
            .mappings()
            .all()
        )
        assert {row["resource"] for row in rows} >= {
            "crm_contact_imports",
            "crm_contact_lists",
            "crm_owner_workspaces",
        }
        assert all(row["actor_id"] == own.user and row["request_id"] for row in rows)
        await pg_session.rollback()
    assert (
        await pg_session.exec(
            text("""
        SELECT count(*) FROM crm_inbound_enquiries
        WHERE organization_id IN (:a, :b) AND status='new'
    """),
            params={"a": tenants["A"].org, "b": tenants["B"].org},
        )
    ).scalar_one() == 2
    assert (
        await pg_session.exec(
            text("""
        SELECT count(*) FROM crm_inbound_notes WHERE organization_id IN (:a, :b)
    """),
            params={"a": tenants["A"].org, "b": tenants["B"].org},
        )
    ).scalar_one() == 0


async def test_revoked_mock_membership_cannot_reuse_warm_private_cache(tenant_http):
    client, tenants, storage = tenant_http
    headers = {"x-test-identity": "A"}
    assert (await client.get("/api/v1/crm/owners/shared-owner", headers=headers)).status_code == 200
    tenants["A"].active = False
    before = storage.download.await_count
    for path in (
        "/owners/shared-owner",
        "/owner-registry",
        "/owner-workspaces",
        f"/contact-imports/{tenants['A'].source_id}/dropped-rows",
    ):
        assert (await client.get("/api/v1/crm" + path, headers=headers)).status_code == 403
    assert storage.download.await_count == before


@pytest.fixture
async def real_auth_http(pg_session):
    """Only identity is mocked: membership/org/subscription checks use the shared DB session."""
    install_actor_context(pg_session.bind)
    tenants = {key: await seed_tenant(pg_session, key) for key in ("A", "B")}
    for identity, tenant in tenants.items():
        pg_session.add(
            Organization(
                id=tenant.org,
                name=f"Synthetic auth tenant {identity}",
                subscription_status="active",
            )
        )
    await pg_session.flush()
    for tenant in tenants.values():
        pg_session.add(OrganizationMembership(organization_id=tenant.org, user_id=tenant.user))
    await pg_session.commit()
    app = FastAPI()
    app.include_router(router)

    async def identity(request: Request):
        return SimpleNamespace(id=tenants[request.headers["x-test-identity"]].user)

    async def database():
        async with AsyncSession(pg_session.bind, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[require_auth] = identity
    app.dependency_overrides[get_db_session] = database
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        yield client, tenants


async def test_auth_database_transaction_attributes_first_and_next_service_commits(
    real_auth_http, pg_session, monkeypatch
):
    """Auth reads start the transaction before the router knows the trusted actor."""
    from app.crm import router as crm_router

    client, tenants = real_auth_http
    own = tenants["A"]
    rename = crm_router.rename_contact_import
    observed = []

    async def twice(db, **arguments):
        # This transaction was already opened by real require_active_subscription.
        observed.append(
            (
                await db.exec(
                    text(
                        "SELECT current_setting('app.actor_id', true), "
                        "current_setting('app.organization_id', true), "
                        "current_setting('app.request_id', true)"
                    )
                )
            ).one()
        )
        await rename(db, **arguments)
        return await rename(db, **{**arguments, "name": "Synthetic second commit"})

    monkeypatch.setattr(crm_router, "rename_contact_import", twice)
    response = await client.patch(
        f"/api/v1/crm/contact-imports/{own.source_id}",
        json={"name": "Synthetic first commit"},
        headers={"x-test-identity": "A"},
    )
    assert response.status_code == 200, response.text
    records = (
        (
            await pg_session.exec(
                text(
                    "SELECT actor_kind, actor_id, organization_id, request_id, resource "
                    "FROM crm_mutation_audit WHERE organization_id=:org AND action='UPDATE' ORDER BY id"
                ),
                params={"org": own.org},
            )
        )
        .mappings()
        .all()
    )
    assert len(records) == 4  # each real service commit changes its import and saved list
    assert {(row["actor_kind"], row["actor_id"], row["organization_id"]) for row in records} == {
        ("user", own.user, own.org)
    }
    correlations = {row["request_id"] for row in records}
    assert len(correlations) == 1 and None not in correlations and "" not in correlations
    assert observed == [(own.user, own.org, next(iter(correlations)))]


async def test_auth_database_transaction_rejects_first_cross_org_write(
    real_auth_http, pg_session, monkeypatch
):
    """A faulty service cannot use the auth-opened transaction to bypass the DB tenant guard."""
    from app.crm import router as crm_router

    client, tenants = real_auth_http
    own, other = tenants["A"], tenants["B"]

    async def faulty_cross_org_rename(db, **arguments):
        await db.exec(
            text("UPDATE crm_contact_imports SET name='Synthetic forbidden write' WHERE id=:id"),
            params={"id": other.source_id},
        )
        await db.commit()
        return await original_rename(db, **arguments)

    original_rename = crm_router.rename_contact_import
    monkeypatch.setattr(crm_router, "rename_contact_import", faulty_cross_org_rename)
    response = await client.patch(
        f"/api/v1/crm/contact-imports/{own.source_id}",
        json={"name": "Synthetic allowed target"},
        headers={"x-test-identity": "A"},
    )
    assert response.status_code == 500  # injected service defect must fail before its commit
    assert (
        await pg_session.exec(
            text("SELECT name FROM crm_contact_imports WHERE id=:id"),
            params={"id": other.source_id},
        )
    ).scalar_one() == "PRIVATE IMPORT B"
    assert (
        await pg_session.exec(
            text(
                "SELECT count(*) FROM crm_mutation_audit WHERE organization_id=:org AND action='UPDATE'"
            ),
            params={"org": other.org},
        )
    ).scalar_one() == 0
