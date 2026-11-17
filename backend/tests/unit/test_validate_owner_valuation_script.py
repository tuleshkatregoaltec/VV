"""The read-only validation command consumes canonical assessed identities, never raw assertions."""

from argparse import Namespace
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.crm.import_models import CrmPropertyContactClaim
from scripts.crm import validate_owner_valuation as script


async def test_sample_accepts_repository_tuples_and_uses_assessed_sale_identity(
    monkeypatch, tmp_path
):
    raw = CrmPropertyContactClaim(
        id=1,
        organization_id="org",
        import_id=1,
        list_id=1,
        source_sheet="Owners",
        source_row_number=1,
        row_fingerprint="row",
        owner_key="owner",
        property_key="raw",
        contact_name="Synthetic",
        ownership_status="unit_linked_unverified",
        match_reason="",
        unit_number="WRONG",
        estimated_value_aed=2_000_000,
        valuation={"confidence": "high", "valued_at": "2026-11-05"},
        created_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
        updated_at=datetime(2026, 11, 5, tzinfo=timezone.utc),
    )
    assessed = dict(
        assessed_status="verified_current_owner",
        unit_number="101",
        latest_sale_date="2020-01-01",
        latest_sale_price_aed=1_000_000,
        area_name="Dubai Marina",
        building_name="Tower",
        project_name="Project",
    )

    class Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def expunge_all(self):
            return None

    monkeypatch.setattr(script, "get_postgres_engine", lambda: object())
    monkeypatch.setattr(script, "async_sessionmaker", lambda *args, **kwargs: Db)
    monkeypatch.setattr(
        script,
        "open_store",
        AsyncMock(return_value=SimpleNamespace(state=SimpleNamespace(generation=7))),
    )
    selected = AsyncMock(return_value=[(raw, assessed)])
    monkeypatch.setattr(script.owner_repository, "list_claims_for_valuation", selected)
    registry = AsyncMock(return_value={})
    monkeypatch.setattr(script, "_registry_rows", registry)
    await script.sample(Namespace(out=str(tmp_path), organization_id="org", size=1, seed=7))
    [canonical] = registry.await_args.args[0]
    assert canonical.unit_number == "101"
    assert canonical.latest_sale_date == date(2020, 1, 1)
    assert raw.unit_number == "WRONG"
    assert selected.await_args.kwargs["generation"] == 7
    assert (tmp_path / "comparables.json").read_text() == "[]"
