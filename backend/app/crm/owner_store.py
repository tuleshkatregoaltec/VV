"""Persisted per-claim ownership assessment, built in bounded chunks.

The whole-organization snapshot in ``owner_assessment`` holds every claim of a tenant as a
Python dict, which costs gigabytes for a few hundred thousand claims. The Owners page only
ever shows a page, one owner, one import or one list, so the assessment is computed once per
(source revision, evidence revision), written to ``crm_owner_assessed_claims`` and read back
by the narrowest key each endpoint has.

A claim's assessment depends on the other claims of the same *property*: competing owners,
a later registry sale, the source lifecycle of that property. The property is only known
once the registry evidence has renamed it, so claims are first assessed in chunks ordered by
their stored property key, and any assessed property that ended up in more than one chunk is
assessed again, whole, in a closed batch. The stored rows are therefore the rows of the
whole-organization assessment.
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import orjson
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.cache import RedisCache
from app.crm import owner_assessment, owner_repository
from app.crm import owner_store_profiles as profiles
from app.crm.source_audit import source_audit_for_row

logger = logging.getLogger(__name__)

CHUNK_CLAIMS = 12_000
INSERT_BATCH = 1_000
# Source-audit rows follow every other row, as they do in the whole-organization snapshot.
SOURCE_ORDER_OFFSET = 1 << 40
SEARCH_FIELDS = (
    "contact_name",
    "phone_primary",
    "phone_alternate",
    "email_primary",
    "area_name",
    "building_name",
    "project_name",
    "unit_number",
)
PROPERTY_SEARCH_FIELDS = (
    "contact_name",
    "area_name",
    "building_name",
    "project_name",
    "unit_number",
)
_BUILD_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


class StoreUnavailable(RuntimeError):
    """The assessment could not be built from stable inputs."""


@dataclass(frozen=True)
class StoreState:
    generation: int
    revision: str
    warehouse_revision: str
    checked_at: datetime
    warehouse_status: str
    built_at: datetime
    summary: dict[str, Any]
    import_summaries: dict[str, Any]
    list_counts: dict[str, Any]
    source_audit: dict[str, Any]


def _search_text(row: dict[str, Any], fields: tuple[str, ...]) -> str:
    return " ".join(str(row.get(field) or "") for field in fields).casefold()


def _ready_row(row: dict[str, Any]) -> bool:
    """The row alone can reach its owner: a leased unit, a current owner and a usable channel."""
    from app.crm import owners
    from app.crm.identity import has_usable_contact

    return bool(
        row["property_identity"] is not None
        and row.get("lead_id")
        and row.get("unit_candidate_key")
        and owners._source_contact_ready(row["assessed_status"], row.get("party_role"))
        and owners._source_contact_ready(
            row.get("event_assessed_status", row["assessed_status"]), row.get("party_role")
        )
        and has_usable_contact(
            row.get("phone_primary"),
            row.get("phone_alternate"),
            row.get("email_primary"),
            row.get("broker_contact"),
        )
    )


def _record(row: dict[str, Any], organization_id: str, generation: int) -> dict[str, Any]:
    """The indexed columns beside one assessed row's JSON."""
    from app.crm import owners

    identity = row["property_identity"]
    is_source = bool(source_audit_for_row(row))
    preference = owners._assessed_row_preference(row)
    transaction_date = row.get("transaction_date")
    return {
        "organization_id": organization_id,
        "generation": generation,
        "claim_id": row["id"],
        "list_id": row["list_id"],
        "import_id": row["import_id"],
        "owner_key": row["owner_key"],
        "canonical_owner_key": row["canonical_owner_key"],
        "property_key": row["property_key"],
        "identity_area": identity[0] if identity else None,
        "identity_key": identity[1] if identity else None,
        "group_ident": f"{identity[0]}\x1f{identity[1]}" if identity else f"source\x1f{row['id']}",
        "is_source": is_source,
        "ord": row["id"] + (SOURCE_ORDER_OFFSET if is_source else 0),
        "assessed_status": row["assessed_status"],
        "party_role": row.get("party_role") or "",
        "transaction_date": transaction_date.isoformat() if transaction_date else None,
        "ready_row": _ready_row(row),
        "event_conf": preference[3],
        "pref_support": preference[0],
        "pref_buyer": preference[1],
        "lead_id": row.get("lead_id"),
        "building_name": row.get("building_name"),
        "project_name": row.get("project_name"),
        "unit_number": row.get("unit_number"),
        "area_name": row.get("area_name"),
        "match_colour": row.get("match_colour"),
        "match_outcome": row.get("match_outcome"),
        "search_text": _search_text(row, SEARCH_FIELDS),
        "props_search_text": _search_text(row, PROPERTY_SEARCH_FIELDS),
        "row": orjson.Fragment(orjson.dumps(row, default=RedisCache._json_default)),
    }


_INSERT = text(
    """
    INSERT INTO crm_owner_assessed_claims (
        organization_id, generation, claim_id, list_id, import_id, owner_key,
        canonical_owner_key, property_key, identity_area, identity_key, group_ident, is_source, ord,
        assessed_status, party_role, transaction_date, event_conf, pref_support, pref_buyer,
        ready_row, lead_id, building_name, project_name, unit_number, area_name, match_colour, match_outcome, search_text, props_search_text, row
    )
    SELECT r.organization_id, r.generation, r.claim_id, r.list_id, r.import_id, r.owner_key,
           r.canonical_owner_key, r.property_key, r.identity_area, r.identity_key, r.group_ident,
           r.is_source, r.ord, r.assessed_status, r.party_role, r.transaction_date, r.event_conf,
           r.pref_support, r.pref_buyer, r.ready_row, r.lead_id, r.building_name, r.project_name, r.unit_number, r.area_name, r.match_colour, r.match_outcome,
           r.search_text, r.props_search_text, r.row
    FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS r(
        organization_id varchar, generation bigint, claim_id integer, list_id integer,
        import_id integer, owner_key varchar, canonical_owner_key varchar,
        property_key varchar, identity_area varchar, identity_key varchar, group_ident varchar,
        is_source boolean, ord bigint, assessed_status varchar, party_role varchar, transaction_date date,
        event_conf integer, pref_support boolean, pref_buyer boolean, ready_row boolean,
        lead_id varchar, building_name varchar, project_name varchar, unit_number varchar, area_name varchar,
        match_colour varchar, match_outcome varchar, search_text text,
        props_search_text text, row jsonb
    )
    """
)


UNAVAILABLE = "unavailable"
UNAVAILABLE_LIFETIME_SECONDS = 10


async def _tokens(db: AsyncSession, organization_id: str) -> tuple[str, str]:
    """The source revision and the registry evidence revision the assessment depends on."""
    revision = await owner_assessment._source_revision(db, organization_id)
    source_only = await owner_repository.owner_sources_only(db, organization_id)
    warehouse = "not_requested" if source_only else await owner_assessment._warehouse_revision()
    return revision, warehouse or UNAVAILABLE


def _json_value(value: Any) -> Any:
    return orjson.loads(value) if isinstance(value, (str, bytes)) else value


async def read_state(db: AsyncSession, organization_id: str) -> StoreState | None:
    result = (
        await db.exec(
            text(
                "SELECT generation, revision, warehouse_revision, checked_at, warehouse_status, "
                "built_at, summary, import_summaries, list_counts, source_audit "
                "FROM crm_owner_assessment_state WHERE organization_id = :org"
            ),
            params={"org": organization_id},
        )
    ).first()
    if not result:
        return None
    return StoreState(*result[:6], *(_json_value(value) for value in result[6:]))


async def _assess_claims(
    engine: AsyncEngine, organization_id: str, claim_ids: list[int], *, degraded: bool
) -> list[dict[str, Any]]:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        rows = await owner_repository.list_owner_history_rows(
            db, organization_id=organization_id, claim_ids=claim_ids
        )
    snapshot = await owner_assessment._build(
        None, organization_id, warehouse_available=not degraded, rows=rows
    )
    if not degraded and snapshot.warehouse_status == "unavailable":
        raise StoreUnavailable("Registry evidence was unavailable while assessing a chunk")
    return snapshot.rows


async def _write(
    engine: AsyncEngine, organization_id: str, generation: int, rows: list[dict[str, Any]]
) -> None:
    records = [_record(row, organization_id, generation) for row in rows]
    async with AsyncSession(engine, expire_on_commit=False) as db:
        for start in range(0, len(records), INSERT_BATCH):
            await db.exec(
                _INSERT,
                params={"payload": orjson.dumps(records[start : start + INSERT_BATCH]).decode()},
            )
        await db.commit()


async def _build_generation(
    engine: AsyncEngine, organization_id: str, generation: int, *, degraded: bool
) -> dict[str, int]:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        ids = [
            row[0]
            for row in (
                await db.exec(
                    text(
                        "SELECT id FROM crm_property_contact_claims "
                        "WHERE organization_id = :org ORDER BY property_key, id"
                    ),
                    params={"org": organization_id},
                )
            ).all()
        ]
    seen: dict[str, int] = {}
    spanning: set[str] = set()
    for index, start in enumerate(range(0, len(ids), CHUNK_CLAIMS)):
        rows = await _assess_claims(
            engine, organization_id, ids[start : start + CHUNK_CLAIMS], degraded=degraded
        )
        for key in {row["property_key"] for row in rows}:
            if seen.setdefault(key, index) != index:
                spanning.add(key)
        await _write(engine, organization_id, generation, rows)
        del rows
        profiles.release_memory()
    del seen
    repaired = 0
    if spanning:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            members = (
                await db.exec(
                    text(
                        "SELECT property_key, claim_id FROM crm_owner_assessed_claims "
                        "WHERE organization_id = :org AND generation = :gen "
                        "AND property_key = ANY(:keys) ORDER BY property_key, claim_id"
                    ),
                    params={"org": organization_id, "gen": generation, "keys": sorted(spanning)},
                )
            ).all()
            await db.exec(
                text(
                    "DELETE FROM crm_owner_assessed_claims WHERE organization_id = :org "
                    "AND generation = :gen AND property_key = ANY(:keys)"
                ),
                params={"org": organization_id, "gen": generation, "keys": sorted(spanning)},
            )
            await db.commit()
        # Whole properties per batch: a batch may exceed the chunk size, never split a property.
        batch: list[int] = []
        last_key = None
        for key, claim_id in members:
            if len(batch) >= CHUNK_CLAIMS and key != last_key:
                rows = await _assess_claims(engine, organization_id, batch, degraded=degraded)
                await _write(engine, organization_id, generation, rows)
                repaired += len(rows)
                batch = []
            batch.append(claim_id)
            last_key = key
        if batch:
            rows = await _assess_claims(engine, organization_id, batch, degraded=degraded)
            await _write(engine, organization_id, generation, rows)
            repaired += len(rows)
    return {"claims": len(ids), "spanning_properties": len(spanning), "repaired_claims": repaired}


async def _next_generation(engine: AsyncEngine) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        return (await db.exec(text("SELECT nextval('crm_owner_assessment_generation_seq')"))).one()[
            0
        ]


async def _finalize(
    engine: AsyncEngine,
    organization_id: str,
    generation: int,
    revision: str,
    warehouse: str,
    *,
    verify_tokens: bool = True,
) -> StoreState:
    """Everything derived from the stored rows, then publish the generation."""
    degraded = warehouse == UNAVAILABLE
    now = datetime.now(timezone.utc)
    totals, stub, results = await profiles.scan(
        engine, organization_id, generation, now, degraded=degraded
    )
    list_counts = await profiles.write_profiles(engine, organization_id, generation, totals, stub)
    del totals
    async with AsyncSession(engine, expire_on_commit=False) as db:
        if verify_tokens and (revision, warehouse) != await _tokens(db, organization_id):
            raise StoreUnavailable("Source or registry evidence changed during the build")
        return await _publish(
            db, organization_id, generation, revision, warehouse, results, list_counts, now
        )


async def rebuild(engine: AsyncEngine, organization_id: str) -> StoreState | None:
    """Assess the organization from stable inputs and publish the result as one generation."""
    async with AsyncSession(engine, expire_on_commit=False) as db:
        revision, warehouse = await _tokens(db, organization_id)
    generation = await _next_generation(engine)
    try:
        stats = await _build_generation(
            engine, organization_id, generation, degraded=warehouse == UNAVAILABLE
        )
        state = await _finalize(engine, organization_id, generation, revision, warehouse)
    except BaseException:
        await _discard(engine, organization_id, keep=None, generation=generation)
        raise
    logger.info("CRM ownership assessment built", extra={"generation": generation, **stats})
    await _discard(engine, organization_id, keep=generation)
    return state


async def store_assessed_rows(
    engine: AsyncEngine,
    organization_id: str,
    rows: list[dict[str, Any]],
    *,
    revision: str,
    warehouse: str,
) -> StoreState:
    """Publish rows that were assessed elsewhere (what a build does after assessing)."""
    generation = await _next_generation(engine)
    await _write(engine, organization_id, generation, rows)
    state = await _finalize(
        engine, organization_id, generation, revision, warehouse, verify_tokens=False
    )
    await _discard(engine, organization_id, keep=generation)
    return state


async def _publish(
    db: AsyncSession,
    organization_id: str,
    generation: int,
    revision: str,
    warehouse: str,
    results: dict[str, Any],
    list_counts: dict[str, dict[str, int]],
    built_at: datetime,
) -> StoreState:
    await db.exec(
        text(
            """
            INSERT INTO crm_owner_assessment_state (
                organization_id, generation, revision, warehouse_revision, checked_at,
                warehouse_status, built_at, summary, import_summaries, list_counts, source_audit
            ) VALUES (
                :org, :gen, :rev, :wh, :checked, :status, :built, CAST(:summary AS jsonb),
                CAST(:imports AS jsonb), CAST(:lists AS jsonb), CAST(:audit AS jsonb)
            )
            ON CONFLICT (organization_id) DO UPDATE SET
                generation = EXCLUDED.generation, revision = EXCLUDED.revision,
                warehouse_revision = EXCLUDED.warehouse_revision,
                checked_at = EXCLUDED.checked_at, warehouse_status = EXCLUDED.warehouse_status,
                built_at = EXCLUDED.built_at, summary = EXCLUDED.summary,
                import_summaries = EXCLUDED.import_summaries,
                list_counts = EXCLUDED.list_counts, source_audit = EXCLUDED.source_audit
            """
        ),
        params={
            "org": organization_id,
            "gen": generation,
            "rev": revision,
            "wh": warehouse,
            "checked": results["checked_at"],
            "status": results["warehouse_status"],
            "built": built_at,
            "summary": orjson.dumps(results["summary"]).decode(),
            "imports": orjson.dumps(results["import_summaries"]).decode(),
            "lists": orjson.dumps(list_counts).decode(),
            "audit": orjson.dumps(results["source_audit"]).decode(),
        },
    )
    await db.commit()
    return StoreState(
        generation,
        revision,
        warehouse,
        results["checked_at"],
        results["warehouse_status"],
        built_at,
        results["summary"],
        results["import_summaries"],
        list_counts,
        results["source_audit"],
    )


async def _discard(
    engine: AsyncEngine, organization_id: str, *, keep: int | None, generation: int | None = None
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db:
        if keep is not None:
            condition, params = "generation <> :gen", {"org": organization_id, "gen": keep}
        else:
            condition, params = "generation = :gen", {"org": organization_id, "gen": generation}
        for table in (
            "crm_owner_registry_properties",
            "crm_owner_registry_owners",
            "crm_owner_assessed_claims",
        ):
            await db.exec(
                text(f"DELETE FROM {table} WHERE organization_id = :org AND {condition}"),
                params=params,
            )
        await db.commit()


STALE_WAIT_SECONDS = 8.0
BUILD_TIMEOUT_SECONDS = 1800.0
_BUILDS: dict[str, asyncio.Task] = {}


async def _build_exclusively(engine: AsyncEngine, organization_id: str) -> StoreState | None:
    """One build per tenant across processes; a second caller just waits for the result."""
    lock = f"owner-assessment:{organization_id}"
    async with engine.connect() as connection:
        got = (
            await connection.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": lock}
            )
        ).scalar()
        if not got:
            return None
        try:
            return await rebuild(engine, organization_id)
        finally:
            await connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": lock}
            )


def _is_current(state: StoreState | None, revision: str, warehouse: str) -> bool:
    if not state or state.revision != revision or state.warehouse_revision != warehouse:
        return False
    # Never keep confirmed-looking labels from, or for long trust, an unavailable lookup.
    age = (datetime.now(timezone.utc) - state.built_at).total_seconds()
    return state.warehouse_status != "unavailable" or age < UNAVAILABLE_LIFETIME_SECONDS


async def open_store(db: AsyncSession, organization_id: str) -> StoreReader:
    """The tenant's current assessment, built first when its inputs have changed.

    A tenant that has an assessment keeps serving it while a new one builds in the
    background, once the wait for the build exceeds ``STALE_WAIT_SECONDS``; a tenant with none
    waits for its first.
    """
    state = await read_state(db, organization_id)
    revision, warehouse = await _tokens(db, organization_id)
    if _is_current(state, revision, warehouse):
        return StoreReader(db, organization_id, state)  # type: ignore[arg-type]
    task = _BUILDS.get(organization_id)
    if task is None or task.done():
        task = asyncio.create_task(_build_exclusively(db.bind, organization_id))  # type: ignore[arg-type]
        _BUILDS[organization_id] = task
    timeout = STALE_WAIT_SECONDS if state else BUILD_TIMEOUT_SECONDS
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout)
    except asyncio.TimeoutError:
        if state is None:
            raise StoreUnavailable("The ownership assessment is still being built") from None
        return StoreReader(db, organization_id, state)
    built = task.result()  # a failed build is this request's failure
    if built is not None:
        return StoreReader(db, organization_id, built)
    # Another process holds the build: wait for its result to be published.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        latest = await read_state(db, organization_id)
        if _is_current(latest, revision, warehouse):
            return StoreReader(db, organization_id, latest)  # type: ignore[arg-type]
        if loop.time() >= deadline:
            if latest is not None:
                return StoreReader(db, organization_id, latest)
            raise StoreUnavailable("The ownership assessment is still being built")
        await asyncio.sleep(1.0)


class StoreReader:
    """Narrow reads of one generation of the stored assessment."""

    def __init__(self, db: AsyncSession, organization_id: str, state: StoreState) -> None:
        self.db = db
        self.organization_id = organization_id
        self.state = state

    @property
    def scope(self) -> dict[str, Any]:
        return {"org": self.organization_id, "gen": self.state.generation}

    def snapshot_stub(self) -> owner_assessment.OwnerAssessmentSnapshot:
        """Carries what row-level summaries read from a snapshot; it holds no rows."""
        return owner_assessment.OwnerAssessmentSnapshot(
            [],
            None,
            self.state.checked_at,
            self.state.warehouse_status,  # type: ignore[arg-type]
        )

    async def rows(
        self, where: str, params: dict[str, Any] | None = None, order: str = "ord"
    ) -> list[dict[str, Any]]:
        result = await self.db.exec(
            text(
                "SELECT row FROM crm_owner_assessed_claims WHERE organization_id = :org "
                f"AND generation = :gen AND {where} ORDER BY {order}"
            ),
            params={**self.scope, **(params or {})},
        )
        return [profiles.row_from_json(value) for (value,) in result.all()]

    async def canonical_owners(self, owner_key: str) -> set[str]:
        """The identities a persisted or canonical owner key stands for."""
        result = await self.db.exec(
            text(
                "SELECT canonical_owner_key FROM crm_owner_assessed_claims "
                "WHERE organization_id = :org AND generation = :gen AND owner_key = :key "
                "UNION SELECT canonical_owner_key FROM crm_owner_assessed_claims "
                "WHERE organization_id = :org AND generation = :gen AND canonical_owner_key = :key"
            ),
            params={**self.scope, "key": owner_key},
        )
        return {row[0] for row in result.all()}

    async def owner_rows(self, canonicals: list[str] | set[str]) -> list[dict[str, Any]]:
        if not canonicals:
            return []
        return await self.rows("canonical_owner_key = ANY(:keys)", {"keys": sorted(canonicals)})

    async def rows_by_ids(self, claim_ids: list[int]) -> list[dict[str, Any]]:
        if not claim_ids:
            return []
        return await self.rows("claim_id = ANY(:ids)", {"ids": sorted(set(claim_ids))})

    async def read_keys(self, canonicals: list[str] | set[str]) -> dict[str, str]:
        """The key each person is shown under, from every row they own."""
        from app.crm import owners

        if not canonicals:
            return {}
        events = (
            await self.db.exec(
                text(
                    "SELECT canonical_owner_key, owner_key, claim_id FROM crm_owner_assessed_claims "
                    "WHERE organization_id = :org AND generation = :gen "
                    "AND canonical_owner_key = ANY(:keys)"
                ),
                params={**self.scope, "keys": sorted(canonicals)},
            )
        ).all()
        owner_keys = sorted({owner_key for _, owner_key, _ in events})
        shared = (
            {
                row[0]
                for row in (
                    await self.db.exec(
                        text(
                            "SELECT owner_key FROM crm_owner_assessed_claims "
                            "WHERE organization_id = :org AND generation = :gen "
                            "AND owner_key = ANY(:keys) "
                            "GROUP BY owner_key HAVING count(DISTINCT canonical_owner_key) > 1"
                        ),
                        params={**self.scope, "keys": owner_keys},
                    )
                ).all()
            }
            if owner_keys
            else set()
        )
        return owners._owner_read_keys(
            [
                {"canonical_owner_key": canonical, "owner_key": owner_key, "id": claim_id}
                for canonical, owner_key, claim_id in events
            ],
            shared_keys=shared,
        )

    async def profile(self, canonical: str, list_id: int = 0):
        from app.crm.import_models import CrmOwnerProfile

        row = (
            await self.db.exec(
                text(
                    "SELECT profile FROM crm_owner_registry_owners WHERE organization_id = :org "
                    "AND generation = :gen AND list_id = :list AND canonical_owner_key = :key"
                ),
                params={**self.scope, "list": list_id, "key": canonical},
            )
        ).first()
        return CrmOwnerProfile.model_validate(_json_value(row[0])) if row else None

    async def has_source_rows(self, canonical: str) -> bool:
        return bool(
            (
                await self.db.exec(
                    text(
                        "SELECT 1 FROM crm_owner_assessed_claims WHERE organization_id = :org "
                        "AND generation = :gen AND canonical_owner_key = :key AND is_source LIMIT 1"
                    ),
                    params={**self.scope, "key": canonical},
                )
            ).first()
        )

    async def property_counts(self, canonicals: set[str]) -> dict[str, int]:
        """Distinct properties per person, by the key the person is shown under."""
        if not canonicals:
            return {}
        read_keys = await self.read_keys(canonicals)
        result = await self.db.exec(
            text(
                "SELECT canonical_owner_key, count(DISTINCT (identity_area, identity_key)) "
                "FROM crm_owner_assessed_claims WHERE organization_id = :org AND generation = :gen "
                "AND canonical_owner_key = ANY(:keys) AND identity_key IS NOT NULL "
                "GROUP BY canonical_owner_key"
            ),
            params={**self.scope, "keys": sorted(canonicals)},
        )
        return {read_keys[canonical]: count for canonical, count in result.all()}

    async def contact_list_groups(
        self,
        list_id: int,
        *,
        search: str | None,
        status: str | None,
        match_colour: list[str] | None,
        match_outcome: list[str] | None,
        limit: int,
        offset: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        """One page of a list's contacts: a contact is one person on one property.

        The row a contact shows is its preferred row; its status is its first row's. Contacts
        keep the order of their first row.
        """
        term = search.strip().casefold() if search else None
        best_first = (
            "ORDER BY pref_support DESC, pref_buyer DESC, transaction_date DESC NULLS LAST, "
            "event_conf DESC, claim_id DESC"
        )
        params = {
            **self.scope,
            "list": list_id,
            "term": term,
            "status": status,
            "colours": match_colour or None,
            "outcomes": match_outcome or None,
            "limit": limit,
            "offset": offset,
        }
        groups = (
            await self.db.exec(
                text(
                    f"""
                    WITH matching AS (
                        SELECT * FROM crm_owner_assessed_claims
                        WHERE organization_id = :org AND generation = :gen AND list_id = :list
                          AND (CAST(:term AS text) IS NULL OR strpos(search_text, CAST(:term AS text)) > 0)
                    ), contacts AS (
                        SELECT canonical_owner_key, group_ident, count(*) AS n_rows,
                               min(ord) AS first_ord,
                               (array_agg(assessed_status ORDER BY ord))[1] AS first_status,
                               (array_agg(claim_id {best_first}))[1] AS best_id,
                               (array_agg(match_colour {best_first}))[1] AS best_colour,
                               (array_agg(match_outcome {best_first}))[1] AS best_outcome
                        FROM matching GROUP BY canonical_owner_key, group_ident
                    ), kept AS (
                        SELECT * FROM contacts
                        WHERE (CAST(:status AS text) IS NULL OR first_status = CAST(:status AS text))
                          AND (CAST(:colours AS text[]) IS NULL OR best_colour = ANY(CAST(:colours AS text[])))
                          AND (CAST(:outcomes AS text[]) IS NULL OR best_outcome = ANY(CAST(:outcomes AS text[])))
                    )
                    SELECT canonical_owner_key, group_ident, n_rows, best_id,
                           count(*) OVER () AS total
                    FROM kept ORDER BY first_ord LIMIT :limit OFFSET :offset
                    """
                ),
                params=params,
            )
        ).all()
        total = groups[0][4] if groups else 0
        if not groups and offset:
            total = (
                await self.db.exec(
                    text(
                        f"""
                        WITH matching AS (
                            SELECT * FROM crm_owner_assessed_claims
                            WHERE organization_id = :org AND generation = :gen AND list_id = :list
                              AND (CAST(:term AS text) IS NULL
                                   OR strpos(search_text, CAST(:term AS text)) > 0)
                        ), contacts AS (
                            SELECT canonical_owner_key, group_ident,
                                   (array_agg(assessed_status ORDER BY ord))[1] AS first_status,
                                   (array_agg(match_colour {best_first}))[1] AS best_colour,
                                   (array_agg(match_outcome {best_first}))[1] AS best_outcome
                            FROM matching GROUP BY canonical_owner_key, group_ident
                        )
                        SELECT count(*) FROM contacts
                        WHERE (CAST(:status AS text) IS NULL OR first_status = CAST(:status AS text))
                          AND (CAST(:colours AS text[]) IS NULL OR best_colour = ANY(CAST(:colours AS text[])))
                          AND (CAST(:outcomes AS text[]) IS NULL OR best_outcome = ANY(CAST(:outcomes AS text[])))
                        """
                    ),
                    params=params,
                )
            ).one()[0]
        if not groups:
            return total, []
        members = (
            await self.db.exec(
                text(
                    """
                    SELECT canonical_owner_key, group_ident,
                           row->>'source_sheet' || ':' || (row->>'source_row_number')
                    FROM crm_owner_assessed_claims
                    WHERE organization_id = :org AND generation = :gen AND list_id = :list
                      AND (CAST(:term AS text) IS NULL OR strpos(search_text, CAST(:term AS text)) > 0)
                      AND canonical_owner_key = ANY(:owners) AND group_ident = ANY(:idents)
                    """
                ),
                params={
                    **self.scope,
                    "list": list_id,
                    "term": term,
                    "owners": sorted({group[0] for group in groups}),
                    "idents": sorted({group[1] for group in groups}),
                },
            )
        ).all()
        sources: dict[tuple[str, str], set[str]] = {}
        for canonical, ident, source in members:
            sources.setdefault((canonical, ident), set()).add(source)
        return total, [
            {
                "best_id": best_id,
                "rows": rows,
                "source_rows": sorted(sources.get((canonical, ident), ())),
            }
            for canonical, ident, rows, best_id, _ in groups
        ]

    async def import_property_groups(
        self, import_id: int, search: str | None
    ) -> list[dict[str, Any]]:
        """The import's properties (one per assessed identity), each with its first row's names."""
        term = search.strip().casefold() if search else None
        result = await self.db.exec(
            text(
                """
                SELECT identity_area, identity_key, min(ord) AS first_ord,
                       (array_agg(building_name ORDER BY ord))[1],
                       (array_agg(project_name ORDER BY ord))[1],
                       (array_agg(unit_number ORDER BY ord))[1],
                       (array_agg(area_name ORDER BY ord))[1]
                FROM crm_owner_assessed_claims
                WHERE organization_id = :org AND generation = :gen AND import_id = :import
                  AND identity_key IS NOT NULL
                  AND (CAST(:term AS text) IS NULL OR strpos(props_search_text, CAST(:term AS text)) > 0)
                GROUP BY identity_area, identity_key ORDER BY first_ord
                """
            ),
            params={**self.scope, "import": import_id, "term": term},
        )
        return [
            {
                "identity": (area, key),
                "building": building,
                "project": project,
                "unit": unit,
                "area": area_name,
            }
            for area, key, _, building, project, unit, area_name in result.all()
        ]

    async def import_group_rows(
        self, import_id: int, search: str | None, identities: list[tuple[str, str]]
    ) -> list[dict[str, Any]]:
        """Every row of the given properties in this import that the search keeps."""
        if not identities:
            return []
        term = search.strip().casefold() if search else None
        return await self.rows(
            "import_id = :import AND (CAST(:term AS text) IS NULL "
            "OR strpos(props_search_text, CAST(:term AS text)) > 0) "
            "AND identity_key = ANY(:keys) AND identity_area = ANY(:areas)",
            {
                "import": import_id,
                "term": term,
                "keys": sorted({key for _, key in identities}),
                "areas": sorted({area for area, _ in identities}),
            },
        )

    async def identity_rows(self, identities: list[tuple[str, str]]) -> list[dict[str, Any]]:
        """Every row, in any import, on the given properties."""
        if not identities:
            return []
        return await self.rows(
            "identity_key = ANY(:keys) AND identity_area = ANY(:areas)",
            {
                "keys": sorted({key for _, key in identities}),
                "areas": sorted({area for area, _ in identities}),
            },
        )

    async def owner_aliases(
        self, keys: list[str], *, canonical_too: bool = False
    ) -> dict[str, set[str]]:
        """Persisted (and optionally canonical) owner keys to the identities they stand for."""
        if not keys:
            return {}
        result = await self.db.exec(
            text(
                "SELECT owner_key, canonical_owner_key FROM crm_owner_assessed_claims "
                "WHERE organization_id = :org AND generation = :gen "
                + (
                    "AND (owner_key = ANY(:keys) OR canonical_owner_key = ANY(:keys)) "
                    if canonical_too
                    else "AND owner_key = ANY(:keys) "
                )
                + "GROUP BY owner_key, canonical_owner_key"
            ),
            params={**self.scope, "keys": sorted(set(keys))},
        )
        aliases: dict[str, set[str]] = {}
        for owner_key, canonical in result.all():
            aliases.setdefault(owner_key, set()).add(canonical)
            if canonical_too:
                aliases.setdefault(canonical, set()).add(canonical)
        return aliases

    async def ready_owners(self, canonicals: set[str]) -> set[str]:
        """The identities with a row that can reach them: leased unit, current owner, channel."""
        if not canonicals:
            return set()
        result = await self.db.exec(
            text(
                "SELECT DISTINCT canonical_owner_key FROM crm_owner_assessed_claims "
                "WHERE organization_id = :org AND generation = :gen "
                "AND canonical_owner_key = ANY(:keys) AND ready_row"
            ),
            params={**self.scope, "keys": sorted(canonicals)},
        )
        return {row[0] for row in result.all()}

    async def unique_persisted_keys(self, canonicals: set[str]) -> set[str]:
        """The persisted owner keys of these identities that no other identity shares."""
        if not canonicals:
            return set()
        result = await self.db.exec(
            text(
                "SELECT owner_key FROM crm_owner_assessed_claims "
                "WHERE organization_id = :org AND generation = :gen AND owner_key IN ("
                "  SELECT owner_key FROM crm_owner_assessed_claims "
                "  WHERE organization_id = :org AND generation = :gen "
                "  AND canonical_owner_key = ANY(:keys)) "
                "GROUP BY owner_key HAVING count(DISTINCT canonical_owner_key) = 1"
            ),
            params={**self.scope, "keys": sorted(canonicals)},
        )
        return {row[0] for row in result.all()}

    async def registry_page(
        self,
        *,
        list_id: int | None,
        scope: str,
        status: str | None,
        search: str | None,
        lease_window: str | None,
        portfolio_only: bool,
        min_rent_aed: int | None,
        max_rent_aed: int | None,
        min_value_aed: int | None,
        max_value_aed: int | None,
        min_properties: int | None,
        next_event_days: int | None,
        transaction_match_status: str | None,
        today: date,
        limit: int,
        offset: int,
    ) -> tuple[list[str], int, dict[str, int]]:
        """Owners whose properties match, in registry order, and the unfiltered folder counts.

        A property matches when it satisfies the scope and every filter; an owner is listed
        when one does. Where the scope narrows what an owner shows (current or prior owners,
        or a transaction-match filter) the owner is counted and ranked on the matching
        properties alone, otherwise on everything they hold.
        """
        variant = list_id or 0
        term = search.strip().casefold() if search else None
        windows = {"expiring_30": (0, 30), "expiring_60": (30, 60), "expiring_90": (60, 90)}
        conditions = {
            "all": "TRUE",
            "rental_ready": "p.ready",
            "registry": "NOT p.ready AND p.status <> 'former_owner'",
            "current_owners": "p.status IN ('verified_current_owner', 'probable_current_owner')",
            "prior_owners": "p.status = 'former_owner'",
            "needs_review": "p.status IN ('probable_current_owner', 'unit_linked_unverified', "
            "'conflicting_claim', 'insufficient_property_data', 'registry_not_observed', "
            "'unmatched', 'unverified_former_owner')",
        }
        params: dict[str, Any] = {
            **self.scope,
            "list": variant,
            "term": term,
            "status": status,
            "tms": transaction_match_status,
            "today": today,
            "min_rent": min_rent_aed,
            "max_rent": max_rent_aed,
            "min_value": min_value_aed,
            "max_value": max_value_aed,
            "min_properties": min_properties,
            "next_event_days": next_event_days,
            "portfolio_only": portfolio_only,
            "limit": limit,
            "offset": offset,
        }
        property_filters = [conditions[scope]]
        if status:
            property_filters.append("p.status = CAST(:status AS text)")
        if transaction_match_status:
            property_filters.append("p.match_status = CAST(:tms AS text)")
        if search:
            property_filters.append(
                "(strpos(o.search_text, CAST(:term AS text)) > 0 "
                "OR strpos(p.location_text, CAST(:term AS text)) > 0)"
            )
        if lease_window == "expired":
            property_filters.append(
                "p.lease_end IS NOT NULL AND p.lease_end - CAST(:today AS date) < 0"
            )
        elif lease_window in windows:
            params["lease_lower"], params["lease_upper"] = windows[lease_window]
            property_filters.append(
                "p.lease_end IS NOT NULL AND :lease_lower < p.lease_end - CAST(:today AS date) "
                "AND p.lease_end - CAST(:today AS date) <= :lease_upper"
            )
        for column, name, operator in (
            ("p.annual_rent_aed", "min_rent", ">="),
            ("p.annual_rent_aed", "max_rent", "<="),
            ("p.sale_price_aed", "min_value", ">="),
            ("p.sale_price_aed", "max_value", "<="),
        ):
            if params[name] is not None:
                property_filters.append(f"{column} {operator} :{name}")
        numeric_filters = any(
            value is not None
            for value in (lease_window, min_rent_aed, max_rent_aed, min_value_aed, max_value_aed)
        )
        params["invalid_allowed"] = (
            scope in {"all", "registry", "needs_review"}
            and not transaction_match_status
            and status in {None, "insufficient_property_data"}
            and not numeric_filters
        )
        params["review_scope"] = scope == "needs_review"
        params["hide_developers"] = scope == "prior_owners"
        scoped = scope in {"current_owners", "prior_owners"} or bool(transaction_match_status)
        # Sort keys: what the owner is ranked on, the whole profile or just the matches.
        if scoped:
            keys = (
                "COALESCE(s.ready_n, 0) AS ready_n, COALESCE(s.n, 0) AS n, "
                "COALESCE(s.conf, 0) AS conf, s.next_lease AS next_lease"
            )
        else:
            keys = (
                "f.contact_ready_count AS ready_n, f.property_count AS n, "
                "f.highest_confidence_score AS conf, f.next_lease_end AS next_lease"
            )
        where = " AND ".join(property_filters)
        statement = text(
            f"""
                    WITH matched AS (
                        SELECT p.canonical_owner_key, p.ready, p.rental_linked, p.lease_end,
                               p.headline_rank, p.confidence
                        FROM crm_owner_registry_properties p
                        JOIN crm_owner_registry_owners o
                          ON o.organization_id = p.organization_id AND o.generation = p.generation
                         AND o.list_id = p.list_id AND o.canonical_owner_key = p.canonical_owner_key
                        WHERE p.organization_id = :org AND p.generation = :gen
                          AND p.list_id = :list AND {where}
                    ), s AS (
                        SELECT canonical_owner_key, count(*) AS n,
                               count(*) FILTER (WHERE ready) AS ready_n,
                               (array_agg(confidence ORDER BY headline_rank DESC, confidence DESC))[1]
                                   AS conf,
                               min(lease_end) FILTER (WHERE rental_linked AND lease_end IS NOT NULL)
                                   AS next_lease
                        FROM matched GROUP BY canonical_owner_key
                    ), ranked AS (
                        SELECT o.canonical_owner_key, o.owner_key, {keys}
                        FROM crm_owner_registry_owners o
                        JOIN crm_owner_registry_owners f
                          ON f.organization_id = o.organization_id AND f.generation = o.generation
                         AND f.list_id = 0 AND f.canonical_owner_key = o.canonical_owner_key
                        LEFT JOIN s ON s.canonical_owner_key = o.canonical_owner_key
                        WHERE o.organization_id = :org AND o.generation = :gen AND o.list_id = :list
                          AND NOT (:hide_developers AND o.developer_side_seller)
                          AND (
                            s.n > 0
                            OR (:invalid_allowed
                                AND (o.no_properties OR (:review_scope AND o.invalid_identity_sources))
                                AND (CAST(:term AS text) IS NULL
                                     OR strpos(o.search_text, CAST(:term AS text)) > 0))
                          )
                    )
                    SELECT canonical_owner_key, count(*) OVER () AS total FROM ranked
                    WHERE (NOT :portfolio_only OR n >= 2)
                      AND (CAST(:min_properties AS integer) IS NULL
                           OR n >= CAST(:min_properties AS integer))
                      AND (CAST(:next_event_days AS integer) IS NULL
                           OR (next_lease IS NOT NULL AND next_lease >= CAST(:today AS date)
                               AND next_lease <= CAST(:today AS date) + CAST(:next_event_days AS integer)))
                    ORDER BY ready_n DESC, n DESC, conf DESC,
                             COALESCE(next_lease, DATE '9999-12-31'), owner_key COLLATE "C"
                    LIMIT :limit OFFSET :offset
                    """
        )
        page = (await self.db.exec(statement, params=params)).all()
        total = page[0][1] if page else 0
        if not page and offset:
            # past the last page: the total still comes from the same query
            first = (
                await self.db.exec(statement, params={**params, "offset": 0, "limit": 1})
            ).all()
            total = first[0][1] if first else 0
        summary = (
            await self.db.exec(
                text(
                    """
                    SELECT count(*) FILTER (WHERE in_rental), count(*) FILTER (WHERE in_registry),
                           count(*) FILTER (WHERE in_prior), count(*) FILTER (WHERE in_review),
                           count(*) FILTER (WHERE in_multi)
                    FROM crm_owner_registry_owners
                    WHERE organization_id = :org AND generation = :gen AND list_id = :list
                    """
                ),
                params={**self.scope, "list": variant},
            )
        ).one()
        return (
            [row[0] for row in page],
            total,
            dict(
                zip(
                    (
                        "rental_owner_profiles",
                        "registry_owner_profiles",
                        "prior_owner_profiles",
                        "needs_review_profiles",
                        "multi_property_owners",
                    ),
                    summary,
                    strict=True,
                )
            ),
        )
