"""The read-only evaluation must account for source rows and respect event semantics."""

import hashlib
import io
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import UploadFile

from app.crm import import_context, imports, ownership, registry_fallback
from app.crm.brokers import BrokerIndex
from app.crm.import_models import CrmContactImport, CrmContactList
from scripts.crm import audit_owner_import as audit


async def test_audit_retains_source_accounting_without_promoting_a_mortgage(tmp_path, monkeypatch):
    source = tmp_path / "Owners.csv"
    source.write_text(
        "Name,Mobile,Building,Unit,Procedure Name,Party Role,Transaction Date,Price\n"
        "Synthetic Buyer,0501234567,Tower A,101,Sale,Buyer,01/01/2025,1000000\n"
        "Synthetic Borrower,0501234568,Tower A,101,Mortgage,Buyer,01/01/2025,1000000\n"
        ",0501234569,Tower A,102,Sale,Buyer,01/01/2025,1000000\n"
    )
    sale = {
        "transaction_date": date(2025, 1, 1),
        "sale_amount_aed": 1_000_000,
        "building_name": "Tower A",
        "property_type": "Apartment",
        "sale_key": "synthetic-sale",
    }
    for module, name in (
        (import_context, "prepare_file_context"),
        (ownership, "_recover_property_identity_from_transaction"),
        (ownership, "_recover_property_identity_from_near_transaction"),
        (import_context, "recover_from_file_context"),
        (registry_fallback, "_apply_registry_unit_fallbacks"),
    ):
        monkeypatch.setattr(module, name, AsyncMock())
    monkeypatch.setattr(
        ownership, "_sales_evidence", AsyncMock(return_value={"towera|101": [sale]})
    )
    monkeypatch.setattr(ownership, "_rental_evidence", AsyncMock(return_value={}))
    monkeypatch.setattr(audit, "resolve_cadastral_plots", AsyncMock())
    # The property-first matcher has its own tests; this one compares the legacy stages.
    monkeypatch.setattr(audit, "run_owner_matching", AsyncMock())
    monkeypatch.setattr(imports, "run_owner_matching", AsyncMock())
    monkeypatch.setattr(imports, "load_broker_index", AsyncMock(return_value=BrokerIndex()))

    result = await audit.evaluate_file(source)

    assert result["source_rows"] == 3
    assert result["candidate_rows"] == 2
    assert result["dropped_by_reason"] == {"no_name": 1}
    assert result["source_inventory"]["total_rows"] == 3
    assert result["statuses"] == {"unit_linked_unverified": 1, "verified_current_owner": 1}
    assert result["review_signals"]["high_confidence_non_sale_ownership"] == 0
    assert "Synthetic" not in str(result)
    assert "0501234567" not in str(result)

    # Replay is the application's deterministic path. Stub its persistence boundary,
    # then compare its real parser, summary, and ownership decisions with the audit.
    record = CrmContactImport(
        id=1,
        organization_id="synthetic-org",
        created_by_user_id="synthetic-user",
        name="Synthetic",
        original_filename=source.name,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        size_bytes=source.stat().st_size,
        status="completed",
        mapping={},
        summary={},
        created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        imports.import_repository, "lock_import_for_replay", AsyncMock(return_value=record)
    )
    monkeypatch.setattr(
        imports.import_repository, "list_rental_refresh_claims", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        imports.import_repository, "find_import_list", AsyncMock(return_value=CrmContactList(id=1))
    )
    for name in (
        "prepare_file_context",
        "_recover_property_identity_from_transaction",
        "_recover_property_identity_from_near_transaction",
        "recover_from_file_context",
        "_apply_registry_unit_fallbacks",
    ):
        monkeypatch.setattr(imports, name, AsyncMock())
    monkeypatch.setattr(imports, "_sales_evidence", ownership._sales_evidence)
    monkeypatch.setattr(imports, "_rental_evidence", ownership._rental_evidence)
    monkeypatch.setattr(imports, "save_drop_log", AsyncMock(return_value=True))
    monkeypatch.setattr(imports, "_invalidate_owner_summary_cache", MagicMock())
    monkeypatch.setattr(imports, "_import_response", AsyncMock())
    mapper = AsyncMock(side_effect=AssertionError("Replay must not call a model"))
    monkeypatch.setattr(imports, "_llm_mapping", mapper)
    db = MagicMock(commit=AsyncMock(), flush=AsyncMock(), rollback=AsyncMock())
    await imports._execute_contact_import(
        db,
        upload=UploadFile(file=io.BytesIO(source.read_bytes()), filename=source.name),
        name="Synthetic",
        user_id="synthetic-user",
        organization_id="synthetic-org",
        reprocess_import_id=1,
    )
    assert record.summary["total_rows"] == result["source_rows"]
    assert record.summary["candidate_rows"] == result["candidate_rows"]
    assert record.summary["source_property_counts"] == result["source_inventory"]
    assert record.summary["verified_current_owners"] == result["statuses"]["verified_current_owner"]
    assert record.summary["unit_linked_unverified"] == result["statuses"]["unit_linked_unverified"]
    mapper.assert_not_awaited()
