"""The pieces the stored assessment is assembled from give the whole-tenant answer when they
see the tenant one owner at a time."""

from datetime import date

from app.crm import owner_rows as rows_rules
from app.crm.owner_signals import SignalContext, build_owner_signals
from app.crm.source_audit import SourceAuditAccumulator, aggregate_source_audit


def row(id, name, phone, role="Seller", building="Tower A", owner_key=None, **changes):
    base = dict(
        id=id,
        owner_key=owner_key or f"key-{name}",
        canonical_owner_key=f"person-{name}",
        contact_name=name,
        phone_primary=phone,
        phone_alternate=None,
        email_primary=None,
        party_role=role,
        procedure_type="Sale",
        building_name=building,
        property_identity=("area", f"{building}|{id}"),
        list_id=1,
        import_id=1,
        confidence_score=90,
        assessed_status="verified_current_owner",
        transaction_date=date(2025, 1, 1),
    )
    return base | changes


def test_signals_per_owner_equal_signals_over_the_tenant():
    # one phone shared by five names, and a seller of enough units in enough buildings to be a developer
    rows = [row(i, f"name{i}", "0501111111") for i in range(5)]
    rows += [
        row(100 + i, "Big Developer LLC", "0502222222", building=f"Tower {i % 4}")
        for i in range(60)
    ]
    whole = build_owner_signals(rows)
    context = SignalContext()
    for item in rows:
        context.add(item)
    by_owner: dict[str, list] = {}
    for item in rows:
        by_owner.setdefault(item["canonical_owner_key"], []).append(item)
    parts = {}
    for owner_rows in by_owner.values():
        parts |= build_owner_signals(owner_rows, context=context)
    assert parts == whole
    assert whole["person-name0"]["relationship_role"] == "possible_intermediary"
    assert whole["person-Big Developer LLC"]["developer_side_seller"] is True


def test_read_keys_from_shared_keys_equal_read_keys_from_every_row():
    rows = [
        row(1, "a", "1", owner_key="shared"),
        row(2, "b", "2", owner_key="shared"),
        row(3, "b", "2", owner_key="own-b"),
        row(4, "c", "3"),
    ]
    whole = rows_rules.owner_read_keys(rows)
    shared = {"shared"}
    parts = {}
    for canonical in {r["canonical_owner_key"] for r in rows}:
        parts |= rows_rules.owner_read_keys(
            [r for r in rows if r["canonical_owner_key"] == canonical], shared_keys=shared
        )
    assert parts == whole
    assert whole["person-a"] == "person-a"  # its only key is shared, so it is shown by identity
    assert whole["person-b"] == "own-b"


def test_list_counts_add_up_across_owners():
    rows = [
        row(1, "a", "1", role="Buyer", lead_id="l1", unit_candidate_key="u1"),
        row(
            2,
            "a",
            "1",
            role="Buyer",
            lead_id="l1",
            unit_candidate_key="u1",
            property_identity=("area", "Tower A|1"),
        ),
        row(3, "b", "2", role="Buyer", assessed_status="former_owner"),
        row(4, "c", "3", role="Buyer", assessed_status="conflicting_claim"),
    ]
    whole = rows_rules.assessed_list_counts(rows)
    total = dict.fromkeys(whole, 0)
    for canonical in {r["canonical_owner_key"] for r in rows}:
        for key, value in rows_rules.assessed_list_counts(
            [r for r in rows if r["canonical_owner_key"] == canonical]
        ).items():
            total[key] += value
    assert total == whole
    assert whole["total_contacts"] == 3 and whole["former_owners"] == 1


def _audited(id, import_id, reference, disposition, category=None, list_id=1):
    match = {"status": "matched", "owner_category": category, "property_key": f"p{reference}"}
    return {
        "id": id,
        "import_id": import_id,
        "list_id": list_id,
        "source_audit": {
            "reference_id": reference,
            "disposition": disposition,
            "canonical_owner_key": f"owner-{id}",
            "transaction_match": match if category else None,
        },
    }


def test_source_audit_totals_do_not_depend_on_row_order_or_chunking():
    rows = [
        _audited(1, 1, "r1", "owner_candidate", "current"),
        _audited(2, 1, "r1", "owner_candidate", "former"),
        _audited(3, 1, "r2", "excluded_possible_nonownership_transaction"),
        _audited(4, 2, "r3", "owner_candidate", "current", list_id=2),
    ]
    for list_id in (None, 1, 2):
        whole = aggregate_source_audit(rows, list_id)
        accumulator = SourceAuditAccumulator(list_id)
        for item in reversed(rows):
            accumulator.add(item)
        assert accumulator.result() == whole
    assert aggregate_source_audit(rows, 9) is None
