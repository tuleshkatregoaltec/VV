"""Opt-in, local-only real database fixtures for authenticated Market AI evaluation.

Run from backend: python -m scripts.evaluations.market_ai.fixture_snapshot create --user-id UUID
--output /private/path [--postgres-url postgresql://...]. This never creates an auth
user or calls a model. The caller supplies a synthetic local GoTrue identity with an
adequate daily_token_limit. Keep the snapshot until HTTP evaluation finishes, then
use cleanup --snapshot /private/path/snapshot.json with the same local endpoints.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import clickhouse_connect
import psycopg2
from psycopg2 import sql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from scripts.evaluations.market_ai.tracing import fingerprint, private_directory, private_write

BACKEND = Path(__file__).resolve().parents[3]
SCHEMA = BACKEND.parent / "holocron/holocron/lib/sql/clickhouse_schema.sql"
VERSION = "market-ai-local-fixture-1"
REFERENCE = date(2026, 10, 31)
RUNTIME_REFERENCE = date(2026, 11, 4)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DATABASE_NAME = re.compile(r"eval_[a-f0-9]{32}\Z")
ORACLE = {
    "q01": {"total": 10, "price_band_counts": [2, 5, 3], "shares": [0.2, 0.5, 0.3]},
    "q04": {
        "total": 20,
        "New": {"count": 8, "median_aed": 120000},
        "Renewed": {"count": 12, "median_aed": 100000},
    },
}


def local_options(postgres_url=None):
    from app.config import settings

    url = make_url(
        postgres_url or os.environ.get("TEST_POSTGRES_URL") or str(settings.POSTGRES_URL)
    )
    if url.host not in LOCAL_HOSTS or not url.drivername.startswith("postgresql") or url.query:
        raise ValueError("An explicit loopback PostgreSQL URL without query overrides is required")
    if settings.CLICKHOUSE_HOST not in LOCAL_HOSTS:
        raise ValueError("ClickHouse must use a loopback endpoint")
    return url, {
        "host": settings.CLICKHOUSE_HOST,
        "port": settings.CLICKHOUSE_PORT,
        "username": settings.CLICKHOUSE_USER,
        "password": settings.CLICKHOUSE_PASSWORD,
        "secure": settings.CLICKHOUSE_SECURE,
        "connect_timeout": 10,
        "send_receive_timeout": 60,
    }


def fixture_rows():
    """Hand-selected positives plus near misses prove canonical filters actually run."""
    base = {
        "property_usage_en": "Residential",
        "property_type": "Apartment",
        "size_sqm": 100.0,
        "source_system": "dld_open_data",
        "match_status": "dld_only",
        "is_served": 1,
        "built_at": datetime(2026, 11, 4, tzinfo=UTC),
        "geo_method": "label_evidence",
    }
    sales = []
    for index, amount in enumerate(
        [800000, 900000, 1000000, 1200000, 1400000, 1600000, 1800000, 2000000, 2200000, 2400000], 1
    ):
        sales.append(
            {
                **base,
                "row_key": f"S{index}",
                "transaction_id": f"S{index}",
                "instance_date": datetime(2026, 9, index),
                "trans_group_en": "Sales",
                "actual_worth": amount,
                "procedure_area": 100.0,
                "property_type_en": "Unit",
                "property_sub_type_en": "Flat",
                "rooms_en": "1 B/R",
                "area_name_en": "Al Barsha South Fourth",
                "master_project_en": "Jumeirah Village Circle",
                "district_name": "Al Barsha South Fourth",
                "community_key": "jumeirah village circle",
                "community_name": "Jumeirah Village Circle",
                "location_name": "Jumeirah Village Circle",
                "building_name_en": "Synthetic JVC Tower",
                "reg_type_en": "Existing Properties",
            }
        )
    for index, change in enumerate(
        [
            {"trans_group_en": "Mortgages"},
            {"trans_group_en": "Gifts"},
            {"actual_worth": 0},
            {"is_served": 0},
            {"property_type": "Villa"},
            {"instance_date": datetime(2026, 1, 1)},
            {
                "area_name_en": "Business Bay",
                "master_project_en": "Business Bay",
                "district_name": "Business Bay",
                "community_key": "business bay",
                "community_name": "Business Bay",
                "location_name": "Business Bay",
            },
        ],
        1,
    ):
        sales.append(
            {**sales[0], **change, "row_key": f"SX{index}", "transaction_id": f"SX{index}"}
        )
    rentals = []
    for index in range(20):
        amount, version = (120000, "New") if index < 8 else (100000, "Renewed")
        rentals.append(
            {
                **base,
                "row_key": f"R{index}",
                "contract_id": f"R{index}",
                "registration_date": datetime(2026, 9, 1),
                "contract_start_date": datetime(2026, 9, 2),
                "contract_end_date": datetime(2027, 9, 1),
                "annual_amount": amount,
                "contract_amount": amount,
                "actual_area": 100.0,
                "version_en": version,
                "bedrooms": "2 B/R",
                "rooms_en": "2 B/R",
                "ejari_property_sub_type_en": "Flat",
                "area_name_en": "Jumeirah Lakes Towers",
                "master_project_en": "Jumeirah Lakes Towers",
                "district_name": "Al Thanyah Fifth",
                "community_key": "jumeirah lakes towers",
                "community_name": "Jumeirah Lakes Towers",
                "location_name": "Jumeirah Lakes Towers",
                "project_name_en": "Synthetic JLT Tower",
            }
        )
    for index, change in enumerate(
        [
            {"annual_amount": 0},
            {"is_served": 0},
            {"rooms_en": "1 B/R", "bedrooms": "1 B/R"},
            {"contract_end_date": datetime(2026, 8, 1)},
            {"contract_start_date": datetime(2026, 1, 1)},
            {
                "area_name_en": "Business Bay",
                "master_project_en": "Business Bay",
                "district_name": "Business Bay",
                "community_key": "business bay",
                "community_name": "Business Bay",
                "location_name": "Business Bay",
            },
        ],
        1,
    ):
        rentals.append(
            {**rentals[0], **change, "row_key": f"RX{index}", "contract_id": f"RX{index}"}
        )
    return {"sales": sales, "rentals": rentals}


def canonical_ddl(table):
    statements = re.findall(
        rf"^(?:CREATE TABLE IF NOT EXISTS|ALTER TABLE) {re.escape(table)}\b.*?;",
        SCHEMA.read_text(),
        re.S | re.M,
    )
    if not statements or not statements[0].startswith("CREATE"):
        raise ValueError(f"Missing canonical DDL for {table}")
    return statements


async def seed_warehouse(client, rows, releases):
    from scripts.clickhouse.create_compatibility_views import VIEW_DDL

    for table in (
        "market_sale_events",
        "market_rental_events",
        "market_release_ledger",
        "analytics_projects",
        "analytics_buildings",
        "analytics_project_keys",
        "analytics_master_keys",
    ):
        for statement in canonical_ddl(table):
            await client.command(statement.rstrip(";"))
    for view, statement in VIEW_DDL:
        if view in {"ch_transactions", "ch_rent_contracts"}:
            await client.command(statement)
    for alias, community, district, sales, rentals in (
        ("JVC", "Jumeirah Village Circle", "Al Barsha South Fourth", 10, 0),
        ("JLT", "Jumeirah Lakes Towers", "Al Thanyah Fifth", 0, 20),
    ):
        key = re.sub(r"[^a-z0-9]", "", community.lower())
        await client.insert(
            "analytics_projects",
            [
                [
                    key,
                    f"Synthetic {alias} Tower",
                    "Project",
                    key,
                    community,
                    "synthetic_fixture",
                    district,
                    sales,
                    rentals,
                    [community, alias],
                    datetime.now(UTC),
                ]
            ],
            column_names=[
                "project_key",
                "project_name",
                "scope_kind",
                "master_key",
                "master_name",
                "master_source",
                "area_name",
                "sales",
                "leases",
                "spellings",
                "built_at",
            ],
        )
        await client.insert(
            "analytics_master_keys",
            [[raw, key, community, datetime.now(UTC)] for raw in (key, alias.lower())],
            column_names=["raw_key", "master_key", "master_name", "built_at"],
        )
    for source, table in (("sales", "market_sale_events"), ("rentals", "market_rental_events")):
        columns = [*rows[source][0], "release_id"]
        values = [[*row.values(), releases[source]] for row in rows[source]]
        await client.insert(table, values, column_names=columns)
        version = f"{table}__r{releases[source]}"
        await client.command(f"CREATE TABLE {version} AS {table}")
        await client.command(f"INSERT INTO {version} SELECT * FROM {table}")
        await client.insert(
            "market_release_ledger",
            [
                [
                    releases[source],
                    table,
                    "published",
                    VERSION,
                    datetime.now(UTC),
                    datetime.now(UTC),
                    json.dumps(
                        {
                            "ranges": [
                                {"from": "2026-08-01", "to": "2026-11-04", "status": "verified"}
                            ]
                        }
                    ),
                ]
            ],
            column_names=[
                "release_id",
                "dataset",
                "state",
                "owner",
                "started_at",
                "updated_at",
                "coverage_json",
            ],
        )


async def seed_postgres(url, user_id, organization_id):
    from app.billing.models import Subscription
    from app.organization.models import Organization, OrganizationMembership
    from app.token_usage.models import UserTokenUsage

    engine = create_async_engine(url)
    now = datetime.now(UTC)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    Organization(
                        id=organization_id,
                        name="Synthetic assistant evaluation",
                        subscription_status="active",
                    ),
                ]
            )
            await session.flush()
            session.add(
                OrganizationMembership(
                    user_id=user_id, organization_id=organization_id, role="member"
                )
            )
            session.add(
                Subscription(
                    id=str(uuid4()),
                    organization_id=organization_id,
                    stripe_subscription_id="synthetic_" + uuid4().hex,
                    stripe_customer_id="synthetic_customer",
                    stripe_price_id="synthetic_price",
                    status="active",
                    seats=1,
                    current_period_start=now,
                    current_period_end=now + timedelta(days=30),
                )
            )
            session.add(UserTokenUsage(user_id=user_id, date=now.date()))
            await session.commit()
    finally:
        await engine.dispose()


def validate_manifest(value):
    name = value.get("snapshot_id", "")
    if not DATABASE_NAME.fullmatch(name) or any(
        value.get(key) != name for key in ("postgres_database", "clickhouse_database")
    ):
        raise ValueError("Snapshot must identify one uniquely named eval_ database pair")
    if value.get("version") != VERSION or not re.fullmatch(
        r"[a-f0-9]{64}", value.get("owner_token", "")
    ):
        raise ValueError("Invalid snapshot ownership marker")
    if value.get("reference_sha256") != fingerprint(value.get("oracle")):
        raise ValueError("Snapshot oracle digest does not match")
    return name


def pg_admin(url):
    connection = psycopg2.connect(
        url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    )
    connection.autocommit = True
    return connection


def stable_payload(value):
    """Normalize database timestamp representations without changing business values."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: stable_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [stable_payload(item) for item in value]
    return value


async def snapshot_payload(snapshot, client):
    """Read and validate stable data; HTTP conversation/usage writes are deliberately absent."""
    validate_manifest(snapshot)
    fixtures = fixture_rows()
    releases = snapshot.get("release_ids", {})
    if set(releases) != {"sales", "rentals"} or any(
        not re.fullmatch(r"[a-f0-9]{12}", value) for value in releases.values()
    ):
        raise ValueError("Invalid immutable release identifiers")
    if snapshot.get("fixture_sha256") != fingerprint(fixtures):
        raise ValueError("Snapshot seed fixture digest does not match this fixture version")
    payload = {}
    for source, table, view in (
        ("sales", "market_sale_events", "ch_transactions"),
        ("rentals", "market_rental_events", "ch_rent_contracts"),
    ):
        expected = sorted(
            [{**row, "release_id": releases[source]} for row in fixtures[source]],
            key=lambda row: row["row_key"],
        )
        columns = list(expected[0])
        for target in (table, f"{table}__r{releases[source]}", view):
            result = await client.query(
                f"SELECT {', '.join(columns)} FROM {target} ORDER BY row_key"
            )
            actual = [dict(zip(result.column_names, row)) for row in result.result_rows]
            selected = [row for row in expected if row["is_served"]] if target == view else expected
            if stable_payload(actual) != stable_payload(selected):
                raise ValueError(f"Snapshot market payload differs from exact seed in {target}")
            payload[target] = actual
    return stable_payload(payload)


async def verify_snapshot(snapshot, client):
    from app.analytics.market_metrics import get_market_metrics
    from app.analytics.models import MarketMetricsRequest
    from app.analytics.service import get_project_search
    from app.clickhouse import client as warehouse
    from app.market.releases import pin_market_release

    validate_manifest(snapshot)
    payload = await snapshot_payload(snapshot, client)
    if snapshot.get("payload_sha256") != fingerprint(payload):
        raise ValueError("Snapshot stable payload digest does not match the recorded baseline")
    previous = warehouse._client
    warehouse._client = client  # Bind a real isolated client; no query/service is mocked.
    try:
        for alias, community in (
            ("JVC", "Jumeirah Village Circle"),
            ("JLT", "Jumeirah Lakes Towers"),
        ):
            found = await get_project_search(alias)
            if not any(
                item.name == community and item.filter_type == "master" for item in found.projects
            ):
                raise ValueError(f"Canonical location search does not resolve {alias}")
        async with pin_market_release() as pin:
            if (
                pin.missing
                or {key: item.release_id for key, item in pin.versions.items()}
                != snapshot["release_ids"]
            ):
                raise ValueError("The published immutable releases do not match the snapshot")
            for reference in (REFERENCE, RUNTIME_REFERENCE):
                common = {
                    "period": {"type": "rolling_days", "days": 90},
                    "reference_date": reference,
                }
                sales = await get_market_metrics(
                    MarketMetricsRequest(
                        dataset="sales",
                        location="JVC",
                        property_type="apartment",
                        group_by="price_band",
                        price_bands=[1000000, 2000000],
                        metrics=["count"],
                        **common,
                    )
                )
                rentals = await get_market_metrics(
                    MarketMetricsRequest(
                        dataset="rentals",
                        location="JLT",
                        bedrooms=["2"],
                        group_by="contract_version",
                        metrics=["count", "median_aed"],
                        **common,
                    )
                )
                if sales.total.count != 10 or {
                    row.group: (row.count, row.share_of_count) for row in sales.rows
                } != {
                    "under 1,000,000": (2, 0.2),
                    "1,000,000 to under 2,000,000": (5, 0.5),
                    "2,000,000 and above": (3, 0.3),
                }:
                    raise ValueError(
                        "Canonical sale price bands differ from the hand-computed oracle"
                    )
                if rentals.total.count != 20 or {
                    row.group: (row.count, row.values["median_aed"]) for row in rentals.rows
                } != {"New": (8, 120000), "Renewed": (12, 100000)}:
                    raise ValueError(
                        "Canonical rental filters differ from the hand-computed oracle"
                    )
                if sales.coverage.status != "complete" or rentals.coverage.status != "complete":
                    raise ValueError("Snapshot coverage is incomplete")
    finally:
        warehouse._client = previous
    return {
        "sales": 10,
        "rentals": 20,
        "immutable_releases": 2,
        "negative_rows_excluded": True,
        "payload_sha256": fingerprint(payload),
    }


async def create_snapshot(*, user_id, output, postgres_url=None):
    user_id = str(UUID(user_id))
    url, options = local_options(postgres_url)
    output = private_directory(Path(output))
    if (output / "snapshot.json").exists():
        raise ValueError("Output already owns a snapshot; use a new directory")
    name, token = "eval_" + uuid4().hex, uuid4().hex + uuid4().hex
    rows = fixture_rows()
    snapshot = {
        "version": VERSION,
        "snapshot_id": name,
        "postgres_database": name,
        "clickhouse_database": name,
        "owner_token": token,
        "user_id": user_id,
        "organization_id": str(uuid4()),
        "reference_date": REFERENCE.isoformat(),
        "runtime_reference_date": RUNTIME_REFERENCE.isoformat(),
        "fixture_sha256": fingerprint(rows),
        "reference_sha256": fingerprint(ORACLE),
        "oracle": ORACLE,
        "schema_sha256": hashlib.sha256(SCHEMA.read_bytes()).hexdigest(),
        "release_ids": {source: fingerprint(values)[:12] for source, values in rows.items()},
        "auth_requirement": "Existing local synthetic GoTrue user; daily_token_limit >= 24000; no auth records created",
    }
    target = url.set(drivername="postgresql+asyncpg", database=name).render_as_string(
        hide_password=False
    )
    warehouse_admin = await clickhouse_connect.get_async_client(**options)
    admin = None
    created_pg = created_ch = False
    isolated = None
    try:
        admin = pg_admin(url)
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created_pg = True
            cursor.execute(
                sql.SQL("COMMENT ON DATABASE {} IS %s").format(sql.Identifier(name)), (token,)
            )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env={**os.environ, "POSTGRES_URL": target},
            check=True,
            capture_output=True,
            text=True,
        )
        await seed_postgres(target, user_id, snapshot["organization_id"])
        await warehouse_admin.command(f"CREATE DATABASE {name}")
        created_ch = True
        isolated = await clickhouse_connect.get_async_client(**options, database=name)
        await isolated.command(
            "CREATE TABLE evaluation_snapshot_owner (token String) ENGINE = TinyLog"
        )
        await isolated.insert("evaluation_snapshot_owner", [[token]], column_names=["token"])
        await seed_warehouse(isolated, rows, snapshot["release_ids"])
        snapshot["payload_sha256"] = fingerprint(await snapshot_payload(snapshot, isolated))
        snapshot["verification"] = await verify_snapshot(snapshot, isolated)
        private_write(output / "snapshot.json", snapshot)
    except BaseException:
        if created_ch:
            await warehouse_admin.command(f"DROP DATABASE {name} SYNC")
        if created_pg:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
        raise
    finally:
        if isolated is not None:
            await isolated.close()
        await warehouse_admin.close()
        if admin is not None:
            admin.close()
    return output / "snapshot.json"


async def use_snapshot(*, path, postgres_url=None, cleanup=False):
    snapshot = json.loads(Path(path).read_text())
    name = validate_manifest(snapshot)
    url, options = local_options(postgres_url)
    client = await clickhouse_connect.get_async_client(**options)
    admin = isolated = None
    try:
        admin = pg_admin(url)
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
                (name,),
            )
            found = cursor.fetchone()
        present = await client.query(
            "SELECT count() FROM system.databases WHERE name = {name:String}",
            parameters={"name": name},
        )
        has_warehouse = bool(present.result_rows[0][0])
        marker = (
            await client.query(f"SELECT token FROM {name}.evaluation_snapshot_owner")
            if has_warehouse
            else None
        )
        if (found is not None and found != (snapshot["owner_token"],)) or (
            marker is not None and marker.result_rows != [(snapshot["owner_token"],)]
        ):
            raise ValueError("Database ownership markers do not match; refusing access or deletion")
        if not cleanup:
            if found is None or not has_warehouse:
                raise ValueError("Snapshot databases are missing")
            isolated = await clickhouse_connect.get_async_client(**options, database=name)
            return await verify_snapshot(snapshot, isolated)
        # Verify ownership in both databases before dropping either.
        if has_warehouse:
            await client.command(f"DROP DATABASE {name} SYNC")
        if found is not None:
            with admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
                )
        return {"removed": name}
    finally:
        if isolated is not None:
            await isolated.close()
        await client.close()
        if admin is not None:
            admin.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--user-id", required=True)
    create.add_argument("--output", required=True, type=Path)
    for command in (create, commands.add_parser("verify"), commands.add_parser("cleanup")):
        command.add_argument(
            "--postgres-url",
            help="Local PostgreSQL admin URL; otherwise TEST_POSTGRES_URL/settings",
        )
        if command is not create:
            command.add_argument("--snapshot", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "create":
        result = asyncio.run(
            create_snapshot(
                user_id=args.user_id, output=args.output, postgres_url=args.postgres_url
            )
        )
        print(json.dumps({"snapshot": str(result)}))
    else:
        result = asyncio.run(
            use_snapshot(
                path=args.snapshot,
                postgres_url=args.postgres_url,
                cleanup=args.command == "cleanup",
            )
        )
        print(json.dumps(result))


if __name__ == "__main__":
    main()
