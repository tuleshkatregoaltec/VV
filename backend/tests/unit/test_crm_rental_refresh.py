from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.crm import ownership as crm_ownership
from scripts.crm import refresh_rental_imports


def claim(**overrides):
    """The lean link row the refresh reads: no contact, owner or source payload."""
    values = dict(
        id=1,
        import_id=2,
        property_key="tower|101",
        unit_number="101",
        area_name="",
        project_name="",
        lead_id=None,
        unit_candidate_key=None,
        lease_end=None,
        annual_rent_aed=None,
        evidence={},
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def link_store(monkeypatch, rows):
    """Stand in for the claim link reads and writes; returns the written changes."""
    written: list[dict] = []
    reads = AsyncMock(return_value=rows)

    async def save(db, changes, now):
        written.extend(changes)

    monkeypatch.setattr(crm_ownership.import_repository, "list_rental_link_rows", reads)
    monkeypatch.setattr(crm_ownership.import_repository, "save_rental_links", save)
    return written, reads


@pytest.mark.asyncio
async def test_refresh_adds_hits_clears_stale_links_and_writes_only_lease_fields(monkeypatch):
    new = claim()
    old = claim(
        id=2,
        property_key="tower|102",
        unit_number="102",
        lead_id="old-event",
        unit_candidate_key="old-key",
        lease_end=date(2025, 1, 1),
        annual_rent_aed=100000,
    )
    untouched = claim(id=3, property_key="tower|103", unit_number="103")
    written, reads = link_store(monkeypatch, [new, old, untouched])
    db = AsyncMock()
    evidence = AsyncMock(
        return_value={
            "tower|101": {
                "event_key": "new-event",
                "unit_candidate_key": "new-key",
                "lease_end": date(2026, 11, 1),
                "annual_rent_aed": 125000,
            }
        }
    )
    summaries = AsyncMock()
    monkeypatch.setattr(crm_ownership, "_rental_evidence_for_units", evidence)
    monkeypatch.setattr(crm_ownership, "_refresh_contact_import_match_summaries", summaries)
    result = await crm_ownership.refresh_property_contact_rentals(db, organization_id="org")
    assert result == {
        "claims": 3,
        "before_hits": 1,
        "after_hits": 1,
        "added_hits": 1,
        "removed_hits": 1,
        "changed_claims": 2,
    }
    assert written == [
        {
            "id": 1,
            "lead_id": "new-event",
            "unit_candidate_key": "new-key",
            "lease_end": date(2026, 11, 1),
            "annual_rent_aed": 125000,
        },
        {
            "id": 2,
            "lead_id": None,
            "unit_candidate_key": None,
            "lease_end": None,
            "annual_rent_aed": None,
        },
    ]
    reads.assert_awaited_once_with(db, None, "org")
    evidence.assert_awaited_once_with(["101", "102", "103"])
    summaries.assert_awaited_once_with(db, organization_id="org", import_ids={2})
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeated_refresh_does_not_rewrite_existing_links(monkeypatch):
    row = claim(
        lead_id="event",
        unit_candidate_key="key",
        lease_end=date(2026, 11, 1),
        annual_rent_aed=125000,
    )
    written, _ = link_store(monkeypatch, [row])
    db = AsyncMock()
    monkeypatch.setattr(
        crm_ownership,
        "_rental_evidence_for_units",
        AsyncMock(
            return_value={
                row.property_key: {
                    "event_key": "event",
                    "unit_candidate_key": "key",
                    "lease_end": row.lease_end,
                    "annual_rent_aed": 125000,
                }
            }
        ),
    )
    monkeypatch.setattr(crm_ownership, "_refresh_contact_import_match_summaries", AsyncMock())
    result = await crm_ownership.refresh_property_contact_rentals(
        db, organization_id="org", import_id=2, commit=False
    )
    assert result["changed_claims"] == 0
    assert result["after_hits"] == 1
    assert written == []
    db.commit.assert_not_awaited()


async def test_same_building_unit_in_multiple_communities_never_picks_first_lease(monkeypatch):
    rows = [
        {
            "building_name": "Tower 2",
            "unit_number": "402",
            "area_name": area,
            "project_name": project,
            "unit_candidate_key": area,
        }
        for area, project in [
            ("Dubai Science Park", "Opalz"),
            ("Greens", "Golf Towers"),
            ("Jumeirah Village Circle", "May Residence"),
        ]
    ]
    # Missing project metadata alone is not a contradictory identity.
    rows += [
        {
            "building_name": "Unique Tower",
            "unit_number": "402",
            "area_name": "Greens",
            "project_name": project,
        }
        for project in ["", "Golf Towers"]
    ]
    monkeypatch.setattr(
        crm_ownership.owner_queries,
        "fetch_rental_source_columns",
        AsyncMock(return_value=[{"has_unit": 1}]),
    )
    monkeypatch.setattr(
        crm_ownership.owner_queries, "fetch_rental_evidence", AsyncMock(return_value=rows)
    )
    evidence = await crm_ownership._rental_evidence_for_units(["402"])
    assert "tower2|402" not in evidence
    assert "uniquetower|402" in evidence


async def test_rental_refresh_does_not_restore_link_for_colliding_sale_identity(monkeypatch):
    row = claim(lead_id="wrong-event", evidence={"scoped_identity_collision": True})
    written, _ = link_store(monkeypatch, [row])
    db = AsyncMock()
    monkeypatch.setattr(
        crm_ownership,
        "_rental_evidence_for_units",
        AsyncMock(
            return_value={
                row.property_key: {"event_key": "wrong-event", "unit_candidate_key": "other-area"}
            }
        ),
    )
    monkeypatch.setattr(crm_ownership, "_refresh_contact_import_match_summaries", AsyncMock())
    result = await crm_ownership.refresh_property_contact_rentals(db, organization_id="org")
    assert result["removed_hits"] == 1
    assert written[0]["lead_id"] is None and written[0]["unit_candidate_key"] is None


async def test_single_rental_from_another_area_cannot_link_on_shared_display_key(monkeypatch):
    rental = {
        "event_key": "wrong-lease",
        "unit_candidate_key": "wrong-property",
        "area_name": "Dubai Marina",
    }
    row = claim(area_name="Business Bay", lead_id="wrong-lease")
    written, _ = link_store(monkeypatch, [row])
    db = AsyncMock()
    monkeypatch.setattr(
        crm_ownership,
        "_rental_evidence_for_units",
        AsyncMock(return_value={row.property_key: rental}),
    )
    monkeypatch.setattr(crm_ownership, "_refresh_contact_import_match_summaries", AsyncMock())
    result = await crm_ownership.refresh_property_contact_rentals(db, organization_id="org")
    assert result["removed_hits"] == 1
    assert written[0]["unit_candidate_key"] is None


@pytest.mark.asyncio
async def test_failed_warehouse_read_does_not_clear_saved_links(monkeypatch):
    row = claim(lead_id="old-event")
    written, _ = link_store(monkeypatch, [row])
    db = AsyncMock()
    monkeypatch.setattr(
        crm_ownership,
        "_rental_evidence_for_units",
        AsyncMock(side_effect=RuntimeError("Warehouse unavailable")),
    )
    with pytest.raises(RuntimeError, match="Warehouse unavailable"):
        await crm_ownership.refresh_property_contact_rentals(db, organization_id="org")
    assert written == []
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_source_change_aborts_publication_and_leaves_marker_unchanged(monkeypatch, tmp_path):
    db = AsyncMock()
    db.__aenter__.return_value = db
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = ["org"]
    monkeypatch.setattr(refresh_rental_imports, "get_postgres_engine", MagicMock())
    monkeypatch.setattr(refresh_rental_imports, "async_sessionmaker", lambda *a, **k: lambda: db)
    monkeypatch.setattr(
        refresh_rental_imports,
        "rental_snapshot",
        AsyncMock(side_effect=[{"version": 1}, {"version": 2}]),
    )
    monkeypatch.setattr(
        refresh_rental_imports, "claim_snapshot", AsyncMock(return_value={"rows": 1})
    )
    rematch = AsyncMock(return_value={"claims": 1})
    monkeypatch.setattr(crm_ownership, "refresh_property_contact_rentals", rematch)
    with pytest.raises(RuntimeError, match="changed during refresh"):
        await refresh_rental_imports.refresh(tmp_path)
    db.commit.assert_not_awaited()
    assert not (tmp_path / "import-rental-matches.json").exists()


@pytest.mark.asyncio
async def test_dry_run_rolls_back_and_does_not_advance_marker(monkeypatch, tmp_path):
    db = AsyncMock()
    db.__aenter__.return_value = db
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalars.return_value.all.return_value = ["org"]
    monkeypatch.setattr(refresh_rental_imports, "get_postgres_engine", MagicMock())
    monkeypatch.setattr(refresh_rental_imports, "async_sessionmaker", lambda *a, **k: lambda: db)
    monkeypatch.setattr(
        refresh_rental_imports, "rental_snapshot", AsyncMock(return_value={"version": 1})
    )
    monkeypatch.setattr(
        refresh_rental_imports, "claim_snapshot", AsyncMock(return_value={"rows": 1})
    )
    monkeypatch.setattr(
        crm_ownership, "refresh_property_contact_rentals", AsyncMock(return_value={"claims": 1})
    )
    report = await refresh_rental_imports.refresh(tmp_path, dry_run=True)
    assert report["dry_run"]
    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    assert not (tmp_path / "import-rental-matches.json").exists()


def test_link_rows_read_only_the_lease_link_columns_and_lock_them():
    from sqlalchemy.dialects import postgresql

    from app.crm import import_repository

    statement = import_repository.rental_link_statement(None, "org")
    names = [column.name for column in statement.selected_columns]
    assert names == [
        "id",
        "import_id",
        "property_key",
        "unit_number",
        "area_name",
        "project_name",
        "lead_id",
        "unit_candidate_key",
        "lease_end",
        "annual_rent_aed",
        "scoped_identity_collision",
        "registry_property_scope",
    ]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "owner_history_evidence" not in sql
    assert "FOR UPDATE OF crm_property_contact_claims" in sql


@pytest.mark.asyncio
async def test_run_publishes_every_organizations_assessment_after_the_refresh(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        refresh_rental_imports,
        "refresh",
        AsyncMock(side_effect=lambda *a, **k: calls.append("refresh") or {"changed": True}),
    )

    async def publish():
        calls.append("publish")
        return [{"generation": 7}]

    monkeypatch.setattr(refresh_rental_imports, "publish_assessments", publish)
    report = await refresh_rental_imports.run(tmp_path)
    assert calls == ["refresh", "publish"]
    assert report["assessments"] == [{"generation": 7}]


@pytest.mark.asyncio
async def test_run_publishes_even_when_no_lease_link_changed(monkeypatch, tmp_path):
    # A sales load changes the registry evidence the assessment reads without changing links.
    monkeypatch.setattr(
        refresh_rental_imports, "refresh", AsyncMock(return_value={"changed": False})
    )
    publish = AsyncMock(return_value=[])
    monkeypatch.setattr(refresh_rental_imports, "publish_assessments", publish)
    await refresh_rental_imports.run(tmp_path)
    publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_dry_run_publishes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        refresh_rental_imports, "refresh", AsyncMock(return_value={"dry_run": True})
    )
    publish = AsyncMock()
    monkeypatch.setattr(refresh_rental_imports, "publish_assessments", publish)
    await refresh_rental_imports.run(tmp_path, dry_run=True)
    publish.assert_not_awaited()


def _state(generation, revision="r1", warehouse="w1"):
    from app.crm import owner_store

    return owner_store.StoreState(
        generation,
        revision,
        warehouse,
        None,
        "available",
        datetime.now(timezone.utc),
        {},
        {},
        {},
        {},
    )


@pytest.mark.asyncio
async def test_a_current_assessment_is_not_rebuilt(monkeypatch):
    from app.crm import owner_store

    monkeypatch.setattr(owner_store, "read_state", AsyncMock(return_value=_state(3)))
    monkeypatch.setattr(owner_store, "_tokens", AsyncMock(return_value=("r1", "w1")))
    build = AsyncMock()
    monkeypatch.setattr(owner_store, "_build_exclusively", build)
    state = await owner_store.publish_if_stale(MagicMock(), "org")
    assert state.generation == 3
    build.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_stale_assessment_is_rebuilt_and_published(monkeypatch):
    from app.crm import owner_store

    monkeypatch.setattr(owner_store, "read_state", AsyncMock(return_value=_state(3)))
    monkeypatch.setattr(owner_store, "_tokens", AsyncMock(return_value=("r2", "w1")))
    monkeypatch.setattr(
        owner_store, "_build_exclusively", AsyncMock(return_value=_state(4, revision="r2"))
    )
    state = await owner_store.publish_if_stale(MagicMock(), "org")
    assert state.generation == 4


@pytest.mark.asyncio
async def test_inputs_changing_during_a_build_are_retried(monkeypatch):
    from app.crm import owner_store

    monkeypatch.setattr(owner_store, "read_state", AsyncMock(return_value=None))
    monkeypatch.setattr(owner_store, "_tokens", AsyncMock(return_value=("r1", "w1")))
    build = AsyncMock(side_effect=[owner_store.StoreUnavailable("changed"), _state(5)])
    monkeypatch.setattr(owner_store, "_build_exclusively", build)
    state = await owner_store.publish_if_stale(MagicMock(), "org", attempts=2)
    assert state.generation == 5
    assert build.await_count == 2


@pytest.mark.asyncio
async def test_a_build_held_by_another_process_is_waited_for(monkeypatch):
    from app.crm import owner_store

    states = iter([_state(3), _state(3), _state(4, revision="r2")])
    monkeypatch.setattr(owner_store, "read_state", AsyncMock(side_effect=lambda *a: next(states)))
    monkeypatch.setattr(owner_store, "_tokens", AsyncMock(return_value=("r2", "w1")))
    monkeypatch.setattr(owner_store, "_build_exclusively", AsyncMock(return_value=None))
    monkeypatch.setattr(owner_store.asyncio, "sleep", AsyncMock())
    state = await owner_store.publish_if_stale(MagicMock(), "org")
    assert state.generation == 4
