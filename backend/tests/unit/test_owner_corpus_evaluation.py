"""Corpus evaluation preserves hard rows and independent units/events denominators."""

import io
import json
import sqlite3
from datetime import date

import openpyxl
import pytest

from scripts.crm import evaluate_owner_corpus as corpus


def test_selection_is_frozen_without_match_information():
    items = [{"name": f"f{i:03}.xlsx", "bytes": i, "sha256": str(i)} for i in range(207)]
    selected = corpus.select_files(items)
    assert len(selected) == len({row["name"] for row in selected}) == 20
    assert {
        index: sum(row["size_bin"] == index for row in selected) for index in range(1, 6)
    } == dict.fromkeys(range(1, 6), 4)
    assert selected == corpus.select_files(items)
    assert selected != corpus.select_files([{**row, "name": "new" + row["name"]} for row in items])


def test_parser_accounts_rejected_references_and_party_duplicates(tmp_path):
    path = tmp_path / "Tower.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(
        [
            "Name",
            "Area",
            "Project",
            "Building",
            "Unit",
            "Date",
            "Price",
            "Party Type",
            "Procedure Name",
        ]
    )
    sheet.append(
        [
            "Owner A",
            "Area A",
            "Project A",
            "Tower A",
            "101",
            date(2024, 1, 1),
            1000000,
            "Buyer",
            "Sale",
        ]
    )
    sheet.append(
        [
            "Owner B",
            "Area A",
            "Project A",
            "Tower A",
            "101",
            date(2024, 1, 1),
            1000000,
            "Seller",
            "Sale",
        ]
    )
    sheet.append(
        [None, "Area A", "Project A", "Tower A", "102", date(2024, 1, 1), 1100000, "Buyer", "Sale"]
    )
    sheet.append([None] * 9)
    sheet.append(["Owner C", "Area A", "Project A", "Tower A", "103", None, None, "Buyer", "Sale"])
    book.save(path)
    rows = io.StringIO()
    units, events, stats, _ = corpus.parse_workbook(path, rows)
    assert stats["nonblank_data_rows"] == 4
    assert stats["accepted_rows"] == 3
    assert stats["rejected_rows"] == 1
    assert stats["blank_rows"] == 1
    assert len(units) == 3
    assert len(events) == 3
    assert sorted(len(event["provenance"]) for event in events.values()) == [1, 1, 2]
    assert len([json.loads(row) for row in rows.getvalue().splitlines()]) == 4


def test_missing_scope_stays_in_uncertain_denominator():
    key, uncertain = corpus.source_identity({"unit_number": "101"}, ("f", "s", 2))
    assert uncertain
    assert key[0] == "unkeyable"
    assert (
        corpus.source_identity({"unit_number": "101", "building_name": "Tower 1"}, ("f", "s", 2))[0]
        != corpus.source_identity(
            {"unit_number": "101", "building_name": "Tower 2"}, ("f", "s", 3)
        )[0]
    )


@pytest.mark.parametrize(
    ("later_date", "expected_status"),
    [("2025-01-01", "later_unknown_owner"), ("2024-01-01", "ambiguous_latest_registration")],
)
def test_later_observed_sale_never_claims_source_buyer_is_current(
    tmp_path, later_date, expected_status
):
    source = dict(
        amount_aed=1000000,
        area_name="Business Bay",
        project_name="Tower A",
        building_name="Tower A",
        unit_number="101",
        transaction_date="2024-01-01",
        event_family="sale",
    )
    sale = {**source, "event_key": "s1", "sale_amount_aed": 1000000}
    later = {
        **sale,
        "event_key": "s2",
        "amount_aed": 1200000,
        "sale_amount_aed": 1200000,
        "transaction_date": later_date,
    }
    from app.crm.transaction_matching import property_identity

    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE event(family TEXT, amount REAL, identity TEXT, event_date TEXT, payload TEXT)"
    )
    for event in (sale, later):
        db.execute(
            "INSERT INTO event VALUES (?,?,?,?,?)",
            (
                "sale",
                event["amount_aed"],
                corpus.canonical(property_identity(event)),
                event["transaction_date"],
                corpus.canonical(event),
            ),
        )
    events = {
        "event": dict(
            source=source,
            provenance=[("f", "s", 2)],
            parties=[{"role": "Buyer", "name": "PRIVATE"}],
        )
    }
    units = {"unit": dict(event_ids=["event"], uncertain=False)}
    corpus.evaluate(events, units, db, tmp_path)
    assert units["unit"]["owner_status"] == expected_status
    assert units["unit"]["strict_match"]
    assert len(units["unit"]["observed_sale_history"]) == 2


def test_raw_fractional_price_cannot_be_rounded_into_tolerance(tmp_path):
    path = tmp_path / "Tower.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Name", "Building", "Unit", "Date", "Price", "Procedure Name"])
    sheet.append(["Owner", "Tower A", "101", date(2024, 1, 1), 100.49, "Sale"])
    book.save(path)
    _, events, _, _ = corpus.parse_workbook(path, io.StringIO())
    source = next(iter(events.values()))["source"]
    from decimal import Decimal

    from app.crm.transaction_matching import AmountFirstIndex

    assert source["amount_aed"] == Decimal("100.49")
    observed = {**source, "amount_aed": 98, "sale_amount_aed": 98, "event_key": "s1"}
    assert AmountFirstIndex([observed]).match(source).status == "unmatched"


@pytest.mark.parametrize("source_family", ["rental", "contact_snapshot"])
def test_annual_rent_lookup_stays_provisional_and_does_not_prove_owner(tmp_path, source_family):
    source = dict(
        amount_aed=50000,
        area_name="Business Bay",
        building_name="Tower A",
        unit_number="101",
        transaction_date="2024-01-01",
        event_family=source_family,
    )
    rental = {
        **source,
        "amount_aed": 100000,
        "contract_amount_aed": 100000,
        "annual_rent_aed": 50000,
        "event_key": "r1",
        "contract_key": "r1",
        "event_family": "rental",
    }
    from app.crm.transaction_matching import property_identity

    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE event(family TEXT, amount REAL, identity TEXT, event_date TEXT, payload TEXT)"
    )
    db.execute(
        "INSERT INTO event VALUES (?,?,?,?,?)",
        (
            "rental",
            100000,
            corpus.canonical(property_identity(rental)),
            "2024-01-01",
            corpus.canonical(rental),
        ),
    )
    events = {
        "event": dict(
            source=source,
            provenance=[("f", "s", 2)],
            parties=[{"role": "Buyer", "name": "PRIVATE"}],
        )
    }
    units = {"unit": dict(event_ids=["event"], uncertain=False)}
    corpus.evaluate(events, units, db, tmp_path)
    if source_family == "contact_snapshot":
        assert "annualized_amount_basis" in events["event"]["result"]["flags"]
    else:
        assert events["event"]["result"]["status"] == "unmatched"
    assert not units["unit"]["strict_match"]
    assert units["unit"]["provisional_match"]
    if source_family == "rental":
        assert units["unit"]["identity_only_without_amount_match"]
    assert units["unit"]["owner_status"] == "no_registry_supported_buyer"


def test_full_plot_namespace_can_prove_property_without_source_unit_column(tmp_path):
    source = dict(
        amount_aed=1000000,
        area_name="Business Bay",
        building_name="Sector A",
        unit_number="",
        plot_number="006-220",
        property_type="Plot",
        transaction_date="2024-01-01",
        event_family="sale",
    )
    sale = {**source, "unit_number": "006-220", "event_key": "s1", "sale_amount_aed": 1000000}
    from app.crm.transaction_matching import property_identity

    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE event(family TEXT, amount REAL, identity TEXT, event_date TEXT, payload TEXT)"
    )
    db.execute(
        "INSERT INTO event VALUES (?,?,?,?,?)",
        (
            "sale",
            1000000,
            corpus.canonical(property_identity(sale)),
            "2024-01-01",
            corpus.canonical(sale),
        ),
    )
    events = {"event": dict(source=source, provenance=[("f", "s", 2)], parties=[])}
    units = {"plot": dict(event_ids=["event"], uncertain=True)}
    corpus.evaluate(events, units, db, tmp_path)
    assert units["plot"]["strong_property_match"]
    assert events["event"]["result"]["strict"]
    assert not units["plot"]["strict_match"]


@pytest.mark.parametrize(
    ("source_date", "flag"),
    [
        ("2012-12-01", "source_event_date_before_snapshot_start:sale"),
        ("2026-10-28", "source_event_date_after_snapshot_end:sale"),
    ],
)
def test_possible_warehouse_coverage_gap_does_not_shrink_denominators(tmp_path, source_date, flag):
    source = dict(
        amount_aed=1900000,
        area_name="Business Bay",
        building_name="Tower A",
        unit_number="101",
        transaction_date=source_date,
        event_family="sale",
    )
    observed = {
        **source,
        "amount_aed": 1000000,
        "sale_amount_aed": 1000000,
        "transaction_date": "2024-01-01",
        "event_key": "s1",
    }
    from app.crm.transaction_matching import property_identity

    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE event(family TEXT, amount REAL, identity TEXT, event_date TEXT, payload TEXT)"
    )
    db.execute(
        "INSERT INTO event VALUES (?,?,?,?,?)",
        (
            "sale",
            1000000,
            corpus.canonical(property_identity(observed)),
            "2024-01-01",
            corpus.canonical(observed),
        ),
    )
    events = {"event": dict(source=source, provenance=[("f", "s", 2)], parties=[])}
    units = {"unit": dict(event_ids=["event"], uncertain=False)}
    _, issues = corpus.evaluate(events, units, db, tmp_path)
    assert flag in events["event"]["snapshot_coverage_flags"]
    assert issues["no_dxbi_amount_candidate"] == 1
    assert issues["no_amount_candidate_and_date_outside_snapshot_possible_coverage_gap"] == 1
    assert corpus.coverage(units.values(), events.values())["source_units"] == 1
    assert corpus.coverage(units.values(), events.values())["source_event_groups"] == 1


def test_identity_only_property_link_does_not_manufacture_transaction_or_owner(tmp_path):
    source = dict(
        amount_aed=None,
        area_name="Business Bay",
        building_name="The Distinction",
        unit_number="101",
        transaction_date=None,
        event_family="contact_snapshot",
    )
    observed = {
        **source,
        "amount_aed": 1000000,
        "sale_amount_aed": 1000000,
        "transaction_date": "2024-01-01",
        "event_family": "sale",
        "event_key": "s1",
    }
    from app.crm.transaction_matching import property_identity

    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE event(family TEXT, amount REAL, identity TEXT, event_date TEXT, payload TEXT)"
    )
    db.execute(
        "INSERT INTO event VALUES (?,?,?,?,?)",
        (
            "sale",
            1000000,
            corpus.canonical(property_identity(observed)),
            "2024-01-01",
            corpus.canonical(observed),
        ),
    )
    events = {
        "event": dict(
            source=source,
            provenance=[("f", "s", 2)],
            parties=[{"role": "Buyer", "name": "PRIVATE"}],
        )
    }
    units = {"unit": dict(event_ids=["event"], uncertain=False)}
    corpus.evaluate(events, units, db, tmp_path)
    assert events["event"]["result"]["status"] == "unmatched"
    assert events["event"]["property_result"]["status"] == "matched"
    assert events["event"]["property_result"]["event"] is None
    assert units["unit"]["strong_property_match"]
    assert units["unit"]["identity_only_without_amount_match"]
    assert not units["unit"]["strict_match"]
    assert units["unit"]["owner_status"] == "no_registry_supported_buyer"
    counts = corpus.coverage(units.values(), events.values())
    assert counts["provisional_matched_events"] == counts["strict_matched_events"] == 0
    assert counts["provisional_matched_units"] == 1


def test_verified_filename_context_groups_real_unit_and_retains_nameless_row(tmp_path):
    path = tmp_path / "Bella Rose.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Name", "Flat Number", "Date", "Price", "Party Type", "Procedure Name"])
    for name, role in [("Buyer", "Buyer"), ("Seller", "Seller"), (None, "Buyer")]:
        sheet.append([name, "101", date(2024, 1, 1), 1000000, role, "Sale"])
    book.save(path)
    from app.crm.registry_locations import RegistryLocationIndex

    catalog = RegistryLocationIndex(
        [
            dict(
                location_id=1,
                path_key="bella-rose",
                building_key="bellarose",
                area_key="dubaisciencepark",
                match_rank=0,
                building_label="Bella Rose",
                project_label="",
                area_label="Dubai Science Park",
            )
        ]
    )
    audit = io.StringIO()
    units, events, stats, _ = corpus.parse_workbook(path, audit, catalog)
    assert len(units) == len(events) == 1
    assert stats["accepted_rows"] == 2
    assert stats["rejected_rows"] == 1
    unit = next(iter(units.values()))
    assert not unit["uncertain"]
    assert len(unit["provenance"]) == 3
    assert len(unit["raw_source_unit_ids"]) == 3
    rows = [json.loads(line) for line in audit.getvalue().splitlines()]
    assert len(rows) == 3
    assert {row["disposition"] for row in rows} == {"accepted", "no_name"}
    assert all(
        row["inferred_file_context"]["method"] == "filename_exact_dxbi_building" for row in rows
    )


def test_sql_property_scope_prefilter_preserves_full_matcher_decisions():
    from app.crm.transaction_matching import match_property, property_identity

    base = dict(
        area_name="Business Bay",
        project_name="Alpha",
        property_type="Apartment",
        size_sqft=1000,
        sale_amount_aed=1000000,
        amount_aed=1000000,
        transaction_date="2024-01-01",
        event_family="sale",
    )
    events = [
        {**base, "building_name": "Tower A", "unit_number": "101", "event_key": "a"},
        {
            **base,
            "building_name": "Tower A",
            "unit_number": "101",
            "event_key": "a-later",
            "transaction_date": "2025-01-01",
        },
        {**base, "building_name": "Tower B", "unit_number": "101", "event_key": "b"},
        {**base, "building_name": "The Address JBR 1", "unit_number": "101", "event_key": "alias"},
        {
            **base,
            "building_name": "Eden",
            "unit_number": "EDEN-V-13",
            "property_type": "Villa",
            "event_key": "eden",
        },
        {
            **base,
            "building_name": "Other",
            "unit_number": "OTHER-V-13",
            "property_type": "Villa",
            "event_key": "wrong-suffix-scope",
        },
    ]
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE event(family TEXT, amount REAL, identity TEXT, event_date TEXT, payload TEXT)"
    )
    for event in events:
        db.execute(
            "INSERT INTO event VALUES (?,?,?,?,?)",
            (
                "sale",
                event["amount_aed"],
                corpus.canonical(property_identity(event)),
                event["transaction_date"],
                corpus.canonical(event),
            ),
        )
    corpus.ensure_property_lookup(db)
    sources = [
        {"building_name": "Tower A", "project_name": "Alpha", "unit_number": "101"},
        {"building_name": "", "project_name": "Alpha", "unit_number": "101"},
        {"building_name": "Unknown Different Tower", "project_name": "Alpha", "unit_number": "101"},
        {"building_name": "Jumeirah Gate Tower 1", "unit_number": "101"},
        {
            "building_name": "Eden",
            "building_number": "13",
            "unit_number": "13",
            "property_type": "Villa",
        },
        {
            "building_name": "Other",
            "building_number": "13",
            "unit_number": "13",
            "property_type": "Villa",
        },
        {"building_name": "", "project_name": "", "unit_number": "101"},
    ]
    for source in sources:
        source = {"event_family": "contact_snapshot", **source}
        filtered = [json.loads(row[0]) for row in corpus.property_candidate_rows(db, source)]
        full_result, filtered_result = (
            match_property(source, events),
            match_property(source, filtered),
        )
        assert (
            full_result.status,
            full_result.property_identity,
            full_result.flags,
            full_result.property_count,
            full_result.exact_transaction,
        ) == (
            filtered_result.status,
            filtered_result.property_identity,
            filtered_result.flags,
            filtered_result.property_count,
            filtered_result.exact_transaction,
        )
    scoped = [json.loads(row[0]) for row in corpus.property_candidate_rows(db, sources[4])]
    assert {row["event_key"] for row in scoped} == {"eden"}


@pytest.mark.parametrize(
    ("unit", "plot", "alternate", "expected"),
    [
        ("", "AFRA040", "", False),
        ("0", "AFRA040", "", False),
        ("901", "0", "", False),
        ("901", "AFRA040", "", True),
        ("0901", "901", "", False),
        ("AFRA040", "AFRA40", "", False),
        ("901", "0", "AFRA040", True),
    ],
)
def test_guard_replay_selects_all_and_only_changed_identifier_namespace(
    unit, plot, alternate, expected
):
    assert (
        corpus.plot_guard_replay_required(
            {"unit_number": unit, "plot_number": plot, "plot_pre_reg_number": alternate}
        )
        == expected
    )


def test_guard_replay_reconsiders_old_ambiguity_and_keeps_unaffected_results(tmp_path, monkeypatch):
    from dataclasses import asdict

    from app.crm.transaction_matching import AmountFirstIndex, property_identity

    affected = dict(
        unit_number="901",
        plot_number="AFRA040",
        building_name="The Distinction",
        area_name="Business Bay",
        property_type="Apartment",
        amount_aed=1000000,
        transaction_date="2024-01-01",
        event_family="sale",
    )
    unchanged = {**affected, "unit_number": "902", "plot_number": "", "amount_aed": 1200000}
    targets = [
        {
            **affected,
            "unit_number": "AFRA040",
            "property_type": "Plot",
            "event_key": "parent-plot",
            "sale_amount_aed": 1000000,
        },
        {**affected, "event_key": "actual-flat", "sale_amount_aed": 1000000},
        {**unchanged, "event_key": "unchanged-flat", "sale_amount_aed": 1200000},
    ]
    prior = AmountFirstIndex(targets).match(unchanged)
    previous = {
        "changed": {"result": {"status": "ambiguous", "strict": False}},
        "unchanged": {
            "result": {
                **asdict(prior),
                "strict": prior.exact_transaction,
                "strong_property_link": corpus.strong_property_link(prior),
            }
        },
    }
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE event(family TEXT, amount REAL, identity TEXT, event_date TEXT, payload TEXT)"
    )
    for row in targets:
        db.execute(
            "INSERT INTO event VALUES (?,?,?,?,?)",
            (
                "sale",
                row["amount_aed"],
                corpus.canonical(property_identity(row)),
                row["transaction_date"],
                corpus.canonical(row),
            ),
        )
    events = {
        key: dict(source_event_id=key, source=source, provenance=[("f", "s", number)], parties=[])
        for key, source, number in [("changed", affected, 2), ("unchanged", unchanged, 3)]
    }
    units = {
        key: dict(
            event_ids=[key],
            uncertain=False,
            latest_source_buyers=[{"name": "STALE"}],
            observed_sale_history=[{"event_key": "STALE"}],
        )
        for key in events
    }
    calls = []
    real_match = AmountFirstIndex.match

    def tracked_match(self, source):
        calls.append(source["unit_number"])
        return real_match(self, source)

    monkeypatch.setattr(AmountFirstIndex, "match", tracked_match)
    corpus.evaluate(events, units, db, tmp_path, previous, frozenset({"changed"}))
    assert calls == ["901"]
    assert events["changed"]["result"]["event"]["event_key"] == "actual-flat"
    assert events["changed"]["result"]["strict"]
    assert events["unchanged"]["result"] == previous["unchanged"]["result"]
    assert all(
        "latest_source_buyers" not in unit and "observed_sale_history" not in unit
        for unit in units.values()
    )
