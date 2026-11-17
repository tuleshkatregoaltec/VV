import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.engine import make_url

from app.config import settings
from scripts.evaluation import fixture_snapshot as snapshot


def manifest():
    name = "eval_" + "a" * 32
    return {
        "snapshot_id": name,
        "postgres_database": name,
        "clickhouse_database": name,
        "owner_token": "b" * 64,
        "version": snapshot.VERSION,
        "oracle": copy.deepcopy(snapshot.ORACLE),
        "reference_sha256": snapshot.fingerprint(snapshot.ORACLE),
    }


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://fixture@production.example/app",
        "postgresql://fixture@localhost/app?host=production.example",
        "postgresql://fixture@localhost/app?service=production",
        "sqlite:///local.sqlite",
    ],
)
def test_snapshot_rejects_remote_and_indirect_database_endpoints(url):
    with pytest.raises(ValueError, match="loopback PostgreSQL"):
        snapshot.local_options(url)


def test_snapshot_rejects_remote_warehouse_even_with_local_postgres(monkeypatch):
    monkeypatch.setattr(settings, "CLICKHOUSE_HOST", "warehouse.example")
    with pytest.raises(ValueError, match="loopback"):
        snapshot.local_options("postgresql://fixture@localhost/postgres")


@pytest.mark.parametrize(
    "name",
    ["postgres", "vitevue", "eval_existing", "eval_" + "a" * 32 + "; DROP DATABASE postgres"],
)
def test_snapshot_manifest_never_authorizes_general_database_names(name):
    value = manifest()
    value.update(snapshot_id=name, postgres_database=name, clickhouse_database=name)
    with pytest.raises(ValueError, match="uniquely named"):
        snapshot.validate_manifest(value)


def test_snapshot_does_not_accept_mixed_pairs_or_changed_oracle():
    value = manifest()
    value["clickhouse_database"] = "eval_" + "c" * 32
    with pytest.raises(ValueError, match="database pair"):
        snapshot.validate_manifest(value)
    value = manifest()
    value["oracle"]["q04"]["total"] = 99
    with pytest.raises(ValueError, match="digest"):
        snapshot.validate_manifest(value)


async def test_cleanup_rejects_unowned_manifest_before_connecting(tmp_path):
    path = tmp_path / "snapshot.json"
    value = manifest()
    value["owner_token"] = ""
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="ownership marker"):
        await snapshot.use_snapshot(
            path=path, postgres_url="postgresql://fixture@localhost:1/postgres", cleanup=True
        )


def test_canonical_market_ddl_keeps_uniform_columns_and_release_coverage():
    for table in ("market_sale_events", "market_rental_events"):
        statements = snapshot.canonical_ddl(table)
        assert statements[0].startswith(f"CREATE TABLE IF NOT EXISTS {table}")
        assert any("size_sqm" in item for item in statements)
        assert any("community_key" in item for item in statements)
        assert any("release_id" in item for item in statements)
    assert any("coverage_json" in item for item in snapshot.canonical_ddl("market_release_ledger"))


def test_fixture_digest_is_reproducible_and_contains_adversarial_filter_rows():
    rows = snapshot.fixture_rows()
    assert snapshot.fingerprint(rows) == snapshot.fingerprint(snapshot.fixture_rows())
    assert any(row["is_served"] == 0 for row in rows["sales"])
    assert any(row["trans_group_en"] == "Mortgages" for row in rows["sales"])
    assert any(row["property_type"] == "Villa" for row in rows["sales"])
    assert any(row["rooms_en"] == "1 B/R" for row in rows["rentals"])
    assert any(row["contract_end_date"] <= row["contract_start_date"] for row in rows["rentals"])


async def test_exact_payload_rejects_sale_mutation_that_preserves_count_and_price_band():
    value = manifest()
    fixtures = snapshot.fixture_rows()
    value.update(
        fixture_sha256=snapshot.fingerprint(fixtures),
        release_ids={"sales": "a" * 12, "rentals": "b" * 12},
    )
    rows = sorted(
        [{**row, "release_id": "a" * 12} for row in fixtures["sales"]],
        key=lambda row: row["row_key"],
    )
    next(row for row in rows if row["row_key"] == "S1")["actual_worth"] = 850000
    client = SimpleNamespace(
        query=AsyncMock(
            return_value=SimpleNamespace(
                column_names=list(rows[0]),
                result_rows=[list(row.values()) for row in rows],
            )
        )
    )
    with pytest.raises(ValueError, match="market payload differs"):
        await snapshot.snapshot_payload(value, make_url("postgresql://localhost/postgres"), client)
    assert client.query.await_count == 1  # Stop before PostgreSQL or any model can run.


def test_exact_crm_payload_rejects_name_change_with_unchanged_count_status_and_budget():
    value = {
        "organization_id": "11111111-1111-1111-1111-111111111111",
        "user_id": "22222222-2222-2222-2222-222222222222",
    }
    other = "33333333-3333-3333-3333-333333333333"
    rows = []
    for identity, name, status, intent in [
        (101, "Leena Demo", "qualified", "buy"),
        (102, "Omar Demo", "new", "rent"),
        (103, "Nora Demo", "new", "buy"),
        (201, "Colleague Secret", "qualified", "buy"),
        (301, "Other Tenant Secret", "qualified", "buy"),
    ]:
        rows.append(
            {
                "id": identity,
                "contact_id": identity,
                "full_name": name,
                "status": status,
                "intent": intent,
                "record_kind": "opportunity",
                "source": "Manual",
                "source_lead_id": None,
                "phone": None,
                "email": f"fixture-{identity}@example.test",
                "criteria": {"locations": ["JVC"], "bedrooms_min": 1, "budget_max_aed": 1200000}
                if identity == 101
                else {},
                "next_follow_up": snapshot.REFERENCE if identity == 101 else None,
                "organization_id": other if identity == 301 else value["organization_id"],
                "contact_organization_id": other if identity == 301 else value["organization_id"],
                "created_by_user_id": other if identity == 201 else value["user_id"],
                "assigned_user_id": other if identity == 201 else value["user_id"],
            }
        )
    snapshot.validate_seeded_crm(rows, value)
    rows[0]["full_name"] = "Different customer"
    with pytest.raises(ValueError, match="CRM payload differs"):
        snapshot.validate_seeded_crm(rows, value)


def test_payload_timestamp_normalization_preserves_exact_business_values():
    assert snapshot.stable_payload(datetime(2026, 9, 1)) == snapshot.stable_payload(
        datetime(2026, 9, 1, tzinfo=UTC)
    )
    assert snapshot.fingerprint(
        snapshot.stable_payload({"amount": 800000})
    ) != snapshot.fingerprint(snapshot.stable_payload({"amount": 850000}))
