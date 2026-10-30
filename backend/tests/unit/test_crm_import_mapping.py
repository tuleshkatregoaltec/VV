"""Every data column of a new owner workbook gets a role, without leaking owner data.

Aliases map the known layouts. For a new layout the model maps whatever is still unmapped from
headers plus non-personal samples; the answer is saved by header signature and reused, and a
replay never calls the model.
"""

import json
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.crm import ai, imports
from app.crm.ai import _llm_mapping
from app.crm.import_mapping import (
    column_samples,
    header_signature,
    needs_model_mapping,
    saved_sheet_mapping,
)
from app.crm.import_parsing import _inspect_csv

BASE = "NameEn,Mobile,BuildingNameEn,UnitNumber,ProcedureValue"
PERSONAL_VALUES = ("Ahmed Khan", "0501234567", "ahmed@example.com", "784-1990-1234567-1")


def _profile(header_line: str, *rows: str):
    data = (header_line + "\n" + "\n".join(rows) + "\n").encode()
    return _inspect_csv(data, "owners.csv")[0]


def _provider(monkeypatch, answer: dict | Exception):
    """Replace the OpenRouter call; record every request body."""
    calls: list[dict] = []

    async def fake(client, url, **kwargs):
        calls.append(kwargs["json"])
        if isinstance(answer, Exception):
            raise answer
        response = MagicMock()
        response.json.return_value = {"choices": [{"message": {"content": json.dumps(answer)}}]}
        return response

    monkeypatch.setattr(ai, "provider_request", fake)
    return calls


def _lookup(monkeypatch, store: dict):
    """In-memory stand-in for the saved-mapping table, keyed by header signature."""

    async def latest(db, organization_id, signature):
        return store.get(signature)

    monkeypatch.setattr(imports.import_repository, "latest_mapping_for_signature", latest)


async def _resolve(profiles, *, replay=False, saved_sheets=None, override=None):
    return await imports._resolve_sheet_mappings(
        MagicMock(),
        "organization-1",
        profiles,
        replay=replay,
        saved_sheets=saved_sheets,
        override=override,
    )


def test_header_signature_ignores_order_case_and_punctuation():
    first = header_signature(["Villa Ref", "NameEn", "Unit-Number"])
    assert first == header_signature(["unit number", "VILLA_REF", "nameen"])
    assert first != header_signature(["Villa Ref", "NameEn"])


def test_needs_model_when_any_data_column_has_no_role():
    complete = _profile(BASE, "Ahmed Khan,0501234567,Tower A,101,500000")
    assert needs_model_mapping(complete) is False

    extra = _profile(BASE + ",Layout Code", "Ahmed Khan,0501234567,Tower A,101,500000,A1")
    assert needs_model_mapping(extra) is True


@pytest.mark.parametrize(
    "header_line",
    [
        "NameEn,Mobile,BuildingNameEn,UnitNumber",  # no price
        "NameEn,Mobile,BuildingNameEn,ProcedureValue",  # no unit/plot/building number
        "NameEn,Mobile,UnitNumber,ProcedureValue",  # no building/project/master/area
    ],
)
def test_needs_model_when_a_matching_basic_is_missing(header_line):
    assert needs_model_mapping(_profile(header_line, "a,b,c,d")) is True


def test_column_samples_are_capped_distinct_and_non_personal():
    rows = [f"Ahmed Khan,0501234567,Tower A,{n},500000,L{n % 8}" for n in range(1, 40)]
    profile = _profile(BASE + ",Layout Code", *rows)

    samples = column_samples(profile, profile.sample_rows)

    assert samples["Layout Code"] == ["L1", "L2", "L3", "L4", "L5"]
    assert "NameEn" not in samples and "Mobile" not in samples


def test_samples_redact_phone_email_and_emirates_id_inside_other_columns():
    profile = _profile(
        BASE + ",Remarks",
        "Ahmed Khan,0501234567,Tower A,101,500000,call 0501234567",
        "Ahmed Khan,0501234567,Tower A,102,500000,ahmed@example.com",
        "Ahmed Khan,0501234567,Tower A,103,500000,784-1990-1234567-1",
        "Ahmed Khan,0501234567,Tower A,104,500000,+971 50 123 4567",
        "Ahmed Khan,0501234567,Tower A,105,500000,Corner unit",
    )

    samples = column_samples(profile, profile.sample_rows)

    assert samples["Remarks"] == ["<redacted>", "Corner unit"]


async def test_unmapped_data_column_triggers_model_even_when_basics_present(monkeypatch):
    calls = _provider(monkeypatch, {"field_map": {}})
    profile = _profile(BASE + ",Layout Code", "Ahmed Khan,0501234567,Tower A,101,500000,A1")

    await _llm_mapping(profile, column_samples(profile, profile.sample_rows))

    assert len(calls) == 1


async def test_complete_mapping_does_not_call_the_model(monkeypatch):
    calls = _provider(monkeypatch, AssertionError("deterministic mapping must not use the model"))
    profile = _profile(BASE, "Ahmed Khan,0501234567,Tower A,101,500000")

    result = await _llm_mapping(profile, column_samples(profile, profile.sample_rows))

    assert calls == []
    assert result.mapping_source == "heuristic"


async def test_prompt_contains_samples_but_no_personal_values(monkeypatch):
    calls = _provider(monkeypatch, {"field_map": {}})
    profile = _profile(
        BASE + ",Layout Code,Passport No,Remarks",
        "Ahmed Khan,0501234567,Tower A,101,500000,Layout Z9,P1234567,ahmed@example.com",
        "Ahmed Khan,0501234567,Tower A,102,500000,Layout Y8,P7654321,784-1990-1234567-1",
    )

    await _llm_mapping(profile, column_samples(profile, profile.sample_rows))

    body = json.dumps(calls[0])
    assert "Layout Z9" in body and "Layout Y8" in body
    for personal in (*PERSONAL_VALUES, "P1234567", "P7654321"):
        assert personal not in body
    assert not re.search(r"\+?9715\d{8}", body)
    assert "@" not in body
    # Headers are still sent, so the model can see the personal columns exist.
    assert "Passport No" in body
    assert calls[0]["provider"] == {"zdr": True, "data_collection": "deny"}


async def test_unknown_identifier_header_is_mapped_by_model_and_reused_by_signature(monkeypatch):
    header_line = "NameEn,Mobile,BuildingNameEn,ProcedureValue,Villa Ref"
    rows = ("Ahmed Khan,0501234567,Tower A,500000,V-17",)
    store: dict = {}
    _lookup(monkeypatch, store)
    calls = _provider(monkeypatch, {"field_map": {"building_number": "Villa Ref"}})

    (first,) = await _resolve([_profile(header_line, *rows)])

    assert first.field_map["building_number"] == "Villa Ref"
    assert first.mapping_source == "llm"
    assert len(calls) == 1
    store[header_signature([h.key for h in first.headers])] = saved_sheet_mapping(first)

    # A later file whose headers are the same set, in another order and case.
    again = _profile(
        "villa ref,NAMEEN,Mobile,ProcedureValue,BuildingNameEn", "V-9,Sara,0509999999,1,Tower B"
    )
    (second,) = await _resolve([again])

    assert len(calls) == 1, "the saved mapping must be reused without another model call"
    assert second.mapping_source == "reused"
    assert second.field_map["building_number"] == "villa ref"
    assert second.unmapped_headers == []


async def test_model_failure_keeps_heuristic_and_lists_unmapped_data_columns(monkeypatch):
    _lookup(monkeypatch, {})
    _provider(monkeypatch, TimeoutError("OpenRouter is down"))
    profile = _profile(
        BASE + ",Layout Code,Sub Type",
        "Ahmed Khan,0501234567,Tower A,101,500000,A1,Studio",
    )

    (result,) = await _resolve([profile])

    assert result.mapping_source == "heuristic_fallback"
    assert result.field_map["contact_name"] == "NameEn"
    warning = next(w for w in result.warnings if w.startswith("Columns not imported"))
    assert "Layout Code" in warning and "Sub Type" in warning


async def test_failed_model_answer_is_not_reused(monkeypatch):
    profile = _profile(BASE + ",Layout Code", "Ahmed Khan,0501234567,Tower A,101,500000,A1")
    failed = saved_sheet_mapping(profile) | {"mapping_source": "heuristic_fallback"}
    _lookup(monkeypatch, {header_signature([h.key for h in profile.headers]): failed})
    calls = _provider(monkeypatch, {"field_map": {}})

    await _resolve([profile])

    assert len(calls) == 1


async def test_model_cannot_override_existing_mapping(monkeypatch):
    _provider(
        monkeypatch,
        {
            "field_map": {
                "contact_name": "Layout Code",
                "building_number": "Layout Code",
                "bogus_field": "Layout Code",
                "unit_number": "No Such Header",
            }
        },
    )
    profile = _profile(BASE + ",Layout Code", "Ahmed Khan,0501234567,Tower A,101,500000,A1")

    result = await _llm_mapping(profile, column_samples(profile, profile.sample_rows))

    assert result.field_map["contact_name"] == "NameEn"
    assert result.field_map["unit_number"] == "UnitNumber"
    assert "Model suggests contact_name = Layout Code" in result.warnings
    assert result.field_map["building_number"] == "Layout Code"
    assert "bogus_field" not in result.field_map
    assert result.unmapped_headers == []


async def test_model_fallback_entries_extend_the_fallback_map(monkeypatch):
    _provider(monkeypatch, {"fallback_map": {"unit_number": ["Villa Ref", "UnitNumber", "Nope"]}})
    profile = _profile(BASE + ",Villa Ref", "Ahmed Khan,0501234567,Tower A,101,500000,V-1")

    result = await _llm_mapping(profile, column_samples(profile, profile.sample_rows))

    assert result.fallback_map["unit_number"] == ["Villa Ref"]
    assert result.field_map["unit_number"] == "UnitNumber"


async def test_replay_never_calls_model(monkeypatch):
    calls = _provider(monkeypatch, AssertionError("replay must not call the model"))
    lookup = AsyncMock(side_effect=AssertionError("replay reads the record, not other imports"))
    monkeypatch.setattr(imports.import_repository, "latest_mapping_for_signature", lookup)
    profile = _profile(BASE + ",Villa Ref", "Ahmed Khan,0501234567,Tower A,101,500000,V-1")
    saved = saved_sheet_mapping(profile)
    saved.update(
        mapping_source="llm", field_map={**saved["field_map"], "building_number": "Villa Ref"}
    )

    (replayed,) = await _resolve([profile], replay=True, saved_sheets=[saved])

    assert calls == [] and lookup.await_count == 0
    assert replayed.field_map["building_number"] == "Villa Ref"
    assert replayed.mapping_source == "llm"


async def test_replay_of_an_old_record_without_saved_columns_stays_on_heuristics(monkeypatch):
    calls = _provider(monkeypatch, AssertionError("replay must not call the model"))
    profile = _profile(BASE + ",Villa Ref", "Ahmed Khan,0501234567,Tower A,101,500000,V-1")

    (replayed,) = await _resolve([profile], replay=True, saved_sheets=[{"sheet_name": "owners"}])

    assert calls == []
    assert replayed.mapping_source == "heuristic"
    assert replayed.unmapped_headers == ["Villa Ref"]


async def test_user_override_wins_and_skips_the_model(monkeypatch):
    calls = _provider(monkeypatch, AssertionError("an override must not call the model"))
    lookup = AsyncMock(side_effect=AssertionError("an override needs no saved mapping"))
    monkeypatch.setattr(imports.import_repository, "latest_mapping_for_signature", lookup)
    profile = _profile(BASE + ",Villa Ref", "Ahmed Khan,0501234567,Tower A,101,500000,V-1")

    (result,) = await _resolve(
        [profile],
        override={
            "sheets": [
                {
                    "sheet": profile.name,
                    "field_map": {"unit_number": "Villa Ref", "not_a_field": "Villa Ref"},
                }
            ]
        },
    )

    assert calls == []
    assert result.mapping_source == "override"
    assert result.field_map["unit_number"] == "Villa Ref"
    assert "not_a_field" not in result.field_map
    assert result.field_map["contact_name"] == "NameEn"


async def test_second_sheet_with_the_same_headers_reuses_the_first_sheets_answer(monkeypatch):
    _lookup(monkeypatch, {})
    calls = _provider(monkeypatch, {"field_map": {"building_number": "Villa Ref"}})
    header_line = "NameEn,Mobile,BuildingNameEn,ProcedureValue,Villa Ref"
    one = _profile(header_line, "Ahmed Khan,0501234567,Tower A,500000,V-1")
    two = _profile(header_line, "Sara,0509999999,Tower B,600000,V-2")
    two.name = "Sheet2"

    first, second = await _resolve([one, two])

    assert len(calls) == 1
    assert (first.mapping_source, second.mapping_source) == ("llm", "reused")


def _upload(header_line: str, *rows: str):
    from io import BytesIO

    from fastapi import UploadFile

    data = (header_line + "\n" + "\n".join(rows) + "\n").encode()
    return UploadFile(file=BytesIO(data), filename="owners.csv")


async def test_preview_shows_the_field_each_column_feeds_as_the_import_reads_it(monkeypatch):
    # The preview is what the agent checks before importing, so it must agree with the import.
    _provider(monkeypatch, AssertionError("a preview must never call the model"))
    _lookup(monkeypatch, {})
    row = "Ahmed Khan,0501234567,Tower A,101,500000"

    preview = await imports.preview_contact_import(
        MagicMock(), upload=_upload(BASE, row), organization_id="organization-1"
    )
    (imported,) = await _resolve([_profile(BASE, row)])

    (sheet,) = preview.sheets
    assert sheet.rows == 1 and not sheet.mapped_at_import
    by_header = {column.header: column.field for column in sheet.columns}
    assert by_header == {key: field for field, key in imported.field_map.items()}
    assert by_header["BuildingNameEn"] == "building_name"


async def test_preview_reuses_the_mapping_saved_for_the_same_headers(monkeypatch):
    header_line = BASE + ",Villa Ref"
    row = "Ahmed Khan,0501234567,Tower A,101,500000,V-17"
    profile = _profile(header_line, row)
    profile.field_map["building_number"] = "Villa Ref"
    _lookup(
        monkeypatch,
        {header_signature([h.key for h in profile.headers]): saved_sheet_mapping(profile)},
    )
    _provider(monkeypatch, AssertionError("a preview must never call the model"))

    preview = await imports.preview_contact_import(
        MagicMock(), upload=_upload(header_line, row), organization_id="organization-1"
    )

    (sheet,) = preview.sheets
    assert {c.header: c.field for c in sheet.columns}["Villa Ref"] == "building_number"
    assert not sheet.mapped_at_import


async def test_preview_of_new_headers_leaves_unknown_columns_to_the_import(monkeypatch):
    # Without a saved mapping the model maps the column at import; the preview must not guess.
    _lookup(monkeypatch, {})
    calls = _provider(monkeypatch, {"field_map": {"building_number": "Villa Ref"}})

    preview = await imports.preview_contact_import(
        MagicMock(),
        upload=_upload(BASE + ",Villa Ref", "Ahmed Khan,0501234567,Tower A,101,500000,V-17"),
        organization_id="organization-1",
    )

    (sheet,) = preview.sheets
    assert calls == []
    assert {c.header: c.field for c in sheet.columns}["Villa Ref"] is None
    assert sheet.mapped_at_import
