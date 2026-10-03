"""Authorized stored-evidence documents using existing CRM matches and report capabilities."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.core.object_storage import ObjectStorageClient
from app.crm import document_repository as repository
from app.crm.broker import require_enquiry, require_matches
from app.crm.document_models import (
    BrokerDocumentCreate,
    BrokerDocumentData,
    BrokerDocumentGet,
    BrokerDocumentResponse,
    CrmBrokerDocument,
    CrmBrokerMedia,
    DocumentField,
    DocumentMedia,
    DocumentProperty,
    DocumentSection,
)
from app.crm.document_rendering import money, quotation, render_pdf, sanitize_media
from app.crm.reports import get_property_report
from app.market.evidence import MarketAccessContext, bounded_market_read, current_market_release
from app.organization.service import get_membership_for_user, get_organization_by_id
from app.postgres import get_postgres_engine

DOCUMENT_TOOL_MODELS = {
    "create_broker_document": BrokerDocumentCreate,
    "get_broker_document": BrokerDocumentGet,
}
DOCUMENT_DESCRIPTIONS = {
    "create_broker_document": "Queue a private client-ready presentation, comparison, seller evidence pack or draft quotation from selected authorized CRM property match IDs. Reuse returned IDs; no freeform factual prose, HTML or URLs. Charges must be explicitly supplied by the broker, never assumed. Missing charges/availability remain missing. Snapshot preview is authoritative; PDF is downloadable only after the durable worker completes. Idempotency key prevents duplicate jobs.",
    "get_broker_document": "Read an authorized document status and exact persisted preview. A queued/running document is not yet a PDF. Never claim a failed document is ready or distribute it automatically.",
}


def now():
    return datetime.now(timezone.utc)


def document_storage():
    bucket = settings.BROKER_DOCUMENT_STORAGE_BUCKET
    if not bucket or bucket == settings.OBJECT_STORAGE_BUCKET:
        raise HTTPException(503, "Configure a separate private BROKER_DOCUMENT_STORAGE_BUCKET")
    return ObjectStorageClient(
        endpoint_url=str(settings.OBJECT_STORAGE_ENDPOINT_URL)
        if settings.OBJECT_STORAGE_ENDPOINT_URL
        else None,
        access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        bucket_name=bucket,
        region=settings.OBJECT_STORAGE_REGION,
        use_path_style=settings.OBJECT_STORAGE_USE_PATH_STYLE,
    )


def _text(value, maximum=160):
    if value is None or isinstance(value, (dict, list)):
        return None
    return " ".join(str(value).split())[:maximum] or None


def _amount(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and 0 < result <= 1_000_000_000 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def property_snapshot(match, media):
    source = match.snapshot or {}
    listing = match.target_type == "listing"
    fields = [
        ("Location", source.get("area_name")),
        ("Building", source.get("tower_name") or source.get("building_name")),
        ("Project", source.get("project_name") or source.get("subcommunity_name")),
        ("Property type", source.get("property_type")),
        ("Bedrooms", source.get("bedrooms")),
        (
            "Size",
            f"{source['size_value']} {source['size_unit']}"
            if source.get("size_value") and source.get("size_unit")
            else f"{source['size_sqft']} sqft"
            if source.get("size_sqft")
            else None,
        ),
    ]
    facts = [
        DocumentField(label=label, value=value) for label, raw in fields if (value := _text(raw))
    ]
    missing = [label for label, raw in fields if not _text(raw)]
    currency = str(source.get("price_currency") or "Unknown") if listing else "AED"
    # Recorded sale/valuation prices are never relabelled as asking prices.
    asking = _amount(source.get("price_value")) if listing and currency == "AED" else None
    unit = str(source.get("price_period") or "Unknown") if listing else "Asking price not recorded"
    if not asking:
        missing.append("Asking price")
    missing.extend(
        ["Current availability requires confirmation", "Discounts and payment plans not confirmed"]
    )
    if not media:
        missing.append("Approved images and floor plans not supplied")
    title = (
        " · ".join(
            str(value)
            for value in (
                source.get("property_type"),
                source.get("tower_name") or source.get("building_name") or source.get("area_name"),
            )
            if _text(value)
        )
        or "Property evidence"
    )
    return DocumentProperty(
        reference=str(match.target_key),
        title=title[:200],
        facts=facts,
        evidence_date=match.generated_at.isoformat(),
        asking_price=money(asking) if asking is not None else None,
        currency=currency,
        price_unit=unit,
        selling_points=[
            f"{fact.label}: {fact.value}"
            for fact in facts
            if fact.label in {"Building", "Bedrooms", "Size"}
        ],
        trade_offs=[
            "Stored match evidence; current property condition and availability require verification",
            "Recorded asking prices are not achieved prices or a binding offer",
        ],
        missing_information=missing,
        media=[
            DocumentMedia(
                id=item.id,
                kind=item.kind,
                caption="Broker-approved floor plan"
                if item.kind == "floor_plan"
                else "Broker-approved property image",
            )
            for item in media
        ],
    )


async def _seller_sections(matches, context):
    sections = []
    limitations = []
    for match in matches:
        source = match.snapshot or {}
        lead_id = source.get("lead_id") if match.target_type == "unit" else None
        if not lead_id:
            limitations.append(
                f"{match.target_key}: no linked CRM opportunity report; comparable appraisal not supplied."
            )
            continue
        # Reuse the report service, but never its internal agent signals, debt/contact fields,
        # hardcoded selling costs or unverified cross-source valuation conclusions.
        with bounded_market_read():
            report = await get_property_report(str(lead_id), as_of=context.reference_date)
        rows = [
            DocumentField(
                label="Evidence period", value=f"{report.period_start} to {report.period_end}"
            )
        ]
        for comparable in report.sales_comparables[:8]:
            rows.append(
                DocumentField(
                    label=f"Recorded sale {comparable.transaction_date}",
                    value=f"AED {comparable.sale_amount_aed} | {comparable.building_name} | {comparable.size_sqft} sqft",
                )
            )
        sections.append(DocumentSection(title=f"Seller evidence — {match.target_key}", rows=rows))
        release = current_market_release()
        complete = bool(release and release.covers("sales", report.period_start, report.period_end))
        limitations.append(
            "Sales coverage: complete for the pinned period."
            if complete
            else "Sales coverage is unverified; selected comparables are observations, not a complete market or supported valuation."
        )
    limitations.append(
        "No market valuation, assumed selling costs, proceeds, or cross-source yield is included."
    )
    return sections, limitations


async def create_document(db, request: BrokerDocumentCreate, context, *, requirements=None):
    enquiry = await require_enquiry(db, context, request.enquiry_id, request.scope)
    if request.valid_until and request.valid_until < context.reference_date:
        raise HTTPException(422, "Document validity cannot precede the preparation date")
    digest = hashlib.sha256(
        (
            request.model_dump_json() + (requirements.model_dump_json() if requirements else "")
        ).encode()
    ).hexdigest()
    existing = await repository.get_request(db, context, request.idempotency_key)
    if existing:
        if existing.input_hash != digest:
            raise HTTPException(
                409, "Idempotency key already belongs to a different document request"
            )
        await require_enquiry(db, context, request.enquiry_id, request.scope)
        return response(existing)
    seller_instruction = request.kind == "seller_evidence" and enquiry.intent in {"sell", "let"}
    if not seller_instruction:
        await require_matches(
            db,
            context,
            request.enquiry_id,
            request.match_ids,
            scope=request.scope,
            requirements=requirements,
        )
    matches = await repository.selected_matches(
        db, enquiry.id, context.organization_id, request.match_ids
    )
    if len(matches) != len(request.match_ids) or any(
        match.target_type not in {"listing", "unit", "project"}
        or match.state in {"dismissed", "stale"}
        for match in matches
    ):
        raise HTTPException(404, "Selected property evidence not found")
    by_id = {match.id: match for match in matches}
    matches = [by_id[identifier] for identifier in request.match_ids]
    media = await repository.selected_media(
        db, context.organization_id, enquiry.id, request.media_ids
    )
    if len(media) != len(set(request.media_ids)) or any(
        item.match_id not in request.match_ids for item in media
    ):
        raise HTTPException(404, "Approved media not found for the selected properties")
    properties = [
        property_snapshot(match, [item for item in media if item.match_id == match.id])
        for match in matches
    ]
    organization = await get_organization_by_id(db, context.organization_id)
    titles = {
        "presentation": "Property presentation",
        "comparison": "Property comparison shortlist",
        "seller_evidence": "Seller evidence pack",
        "quotation": "Draft property quotation",
    }
    document = BrokerDocumentData(
        brand=organization.name,
        title=titles[request.kind],
        reference=request.reference,
        version=request.version,
        valid_until=request.valid_until,
        prepared_at=now(),
        properties=properties,
        limitations=[
            "Prepared from recorded property evidence.",
            "Property availability, discounts and payment plans are not confirmed.",
            "Evidence dates are recorded snapshot dates; later changes may not be reflected.",
        ],
    )
    if request.kind == "quotation":
        prop = properties[0]
        if prop.currency != request.currency:
            raise HTTPException(
                422,
                "Recorded price currency is unavailable or differs; no currency conversion is inferred",
            )
        document.quotation = quotation(
            prop.asking_price, prop.price_unit, request.charges, request.missing_charges
        )
        document.limitations.append(
            "Draft arithmetic only; estimates are labelled and missing charges are not zero. Fees are broker-supplied, not an approved fee schedule."
        )
    if request.kind == "seller_evidence":
        document.sections, notes = await _seller_sections(matches, context)
        document.limitations.extend(notes)
    # Bound persisted snapshots independently of tool output budgets.
    if len(document.model_dump_json().encode()) > 48 * 1024:
        raise HTTPException(422, "Narrow the document to fit its evidence limit")
    await require_enquiry(db, context, request.enquiry_id, request.scope)
    record = CrmBrokerDocument(
        organization_id=context.organization_id,
        user_id=context.user_id,
        enquiry_id=enquiry.id,
        scope=request.scope,
        kind=request.kind,
        idempotency_key=request.idempotency_key,
        input_hash=digest,
        document_json=document.model_dump(mode="json"),
        created_at=now(),
        updated_at=now(),
    )
    try:
        db.add(record)
        await db.commit()
        await db.refresh(record)
    except IntegrityError:
        await db.rollback()
        existing = await repository.get_request(db, context, request.idempotency_key)
        if not existing or existing.input_hash != digest:
            raise HTTPException(
                409, "Document request conflicted; use a new idempotency key"
            ) from None
        record = existing
    await require_enquiry(db, context, request.enquiry_id, request.scope)
    return response(record)


def response(record):
    data = BrokerDocumentData.model_validate(record.document_json)
    return BrokerDocumentResponse(
        id=record.id,
        status=record.status,
        kind=record.kind,
        title=data.title,
        version=data.version,
        document=data,
        created_at=record.created_at,
        error=record.error,
        download_url=f"/api/v1/crm/broker/documents/{record.id}/download"
        if record.status == "completed"
        else None,
    )


async def authorized_document(db, context, document_id):
    record = await repository.get_document(db, document_id)
    membership = await get_membership_for_user(db, context.user_id)
    if (
        not record
        or record.organization_id != context.organization_id
        or not membership
        or membership.organization_id != context.organization_id
        or (record.user_id != context.user_id and membership.role != "owner")
    ):
        raise HTTPException(404, "Document not found")
    organization = await get_organization_by_id(db, context.organization_id)
    if organization:
        await db.refresh(organization)
    if not organization or organization.subscription_status not in {"active", "trialing"}:
        raise HTTPException(403, "Current organization access is required")
    scope = "organization" if membership.role == "owner" else "mine"
    await require_enquiry(db, context, record.enquiry_id, scope)
    return record


async def document_download(db, context, document_id, storage=None):
    record = await authorized_document(db, context, document_id)
    if record.status != "completed" or not record.object_key:
        raise HTTPException(409, "The PDF is not ready")
    data = await (storage or document_storage()).download(record.object_key)
    if len(data) > 12 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != record.sha256:
        raise HTTPException(503, "Stored document failed its integrity check")
    await authorized_document(db, context, document_id)
    return data


async def approve_media(
    db, context, *, enquiry_id, match_id, kind, data, scope="mine", storage=None
):
    enquiry = await require_enquiry(db, context, enquiry_id, scope)
    if enquiry.intent in {"sell", "let"}:
        matches = await repository.selected_matches(
            db, enquiry_id, context.organization_id, [match_id]
        )
        if (
            len(matches) != 1
            or matches[0].target_type not in {"unit", "listing", "project"}
            or matches[0].state in {"stale", "dismissed"}
        ):
            raise HTTPException(404, "Selected property evidence not found")
    else:
        await require_matches(db, context, enquiry_id, [match_id], scope=scope)
    if kind not in {"image", "floor_plan"}:
        raise HTTPException(422, "Media kind must be image or floor_plan")
    try:
        safe = await asyncio.to_thread(sanitize_media, data)
    except Exception:
        raise HTTPException(422, "Supply a PNG/JPEG image under 4 MiB and 16 megapixels") from None
    item = CrmBrokerMedia(
        organization_id=context.organization_id,
        user_id=context.user_id,
        enquiry_id=enquiry_id,
        match_id=match_id,
        kind=kind,
        object_key="",
        sha256=hashlib.sha256(safe).hexdigest(),
        created_at=now(),
    )
    item.object_key = f"crm/{context.organization_id}/approved-media/{item.id}.jpg"
    store = storage or document_storage()
    await store.upload(item.object_key, safe)
    try:
        await require_enquiry(db, context, enquiry_id, scope)
        db.add(item)
        await db.commit()
    except BaseException:
        await store.delete_many([item.object_key])
        raise
    return DocumentMedia(id=item.id, kind=kind, caption="Broker-approved property media")


async def document_media(db, context, document_id, media_id, storage=None):
    record = await authorized_document(db, context, document_id)
    snapshot = BrokerDocumentData.model_validate(record.document_json)
    if media_id not in {item.id for prop in snapshot.properties for item in prop.media}:
        raise HTTPException(404, "Document media not found")
    items = await repository.selected_media(
        db, context.organization_id, record.enquiry_id, [media_id]
    )
    if not items:
        raise HTTPException(404, "Document media not found")
    data = await (storage or document_storage()).download(items[0].object_key)
    if len(data) > 4 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != items[0].sha256:
        raise HTTPException(503, "Stored media failed its integrity check")
    await authorized_document(db, context, document_id)
    return data


async def execute_document_tool(name, request, context, *, requirements=None):
    async with AsyncSession(get_postgres_engine(), expire_on_commit=False) as db:
        result = (
            await create_document(db, request, context, requirements=requirements)
            if name == "create_broker_document"
            else response(await authorized_document(db, context, request.document_id))
        )
        return result.model_dump(mode="json")


async def process_document_job(db, storage=None):
    record = await repository.claim_document(db, now())
    if not record:
        return False
    token = record.claim_token
    document_id = record.id
    context = MarketAccessContext(
        user_id=record.user_id,
        organization_id=record.organization_id,
        execution_id=f"document:{record.id}",
        reference_date=now().date(),
    )
    key = f"crm/{record.organization_id}/documents/{record.id}/{token}.pdf"
    store = storage
    try:
        async with asyncio.timeout(60):
            await authorized_document(db, context, record.id)
            store = store or document_storage()
            snapshot = BrokerDocumentData.model_validate(record.document_json)
            media = {}
            for prop in snapshot.properties:
                for item in prop.media:
                    media[item.id] = await document_media(
                        db, context, record.id, item.id, storage=store
                    )
            # Rendering performs no I/O; only this validated snapshot and decoded media enter it.
            pdf = await asyncio.to_thread(render_pdf, snapshot, media)
            await store.upload(key, pdf)
            await authorized_document(db, context, record.id)
            saved = await repository.finish_document(
                db,
                document_id,
                token,
                now=now(),
                object_key=key,
                checksum=hashlib.sha256(pdf).hexdigest(),
            )
            if not saved:
                await store.delete_many([key])
    except asyncio.CancelledError:
        # Leave the persisted lease for another worker to reclaim after expiry.
        raise
    except Exception as error:
        await db.rollback()
        code = "render_failed"
        if isinstance(error, HTTPException):
            code = "access_revoked" if error.status_code in {403, 404} else "storage_unavailable"
        elif isinstance(error, ValueError) and str(error) == "unsupported_document_glyph":
            code = "unsupported_document_glyph"
        await repository.finish_document(db, document_id, token, now=now(), error=code)
        if store:
            try:
                await store.delete_many([key])
            except Exception:
                pass
    return True
