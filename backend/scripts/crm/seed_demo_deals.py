"""Seed synthetic deals so the deal board and the manager's Team Deals view show real backend data.

Deals are spread over every agent in the organization's teams, across sale and rent stages,
open / won / lost, with a dated event trail (created, stage moves, closes) so the manager's
"last activity", "won in 30 days" and per-stage figures have something to count.

Every seeded deal carries ``origin_source = DEMO_SOURCE`` and no lead, so the seed never
changes a lead and ``--reset`` removes exactly what it added (events cascade).

    set -a; . ../.env; set +a
    uv run python -m scripts.crm.seed_demo_deals --organization-id <org> --dry-run
    uv run python -m scripts.crm.seed_demo_deals --organization-id <org>
    uv run python -m scripts.crm.seed_demo_deals --organization-id <org> --reset
"""

from __future__ import annotations

import argparse
import asyncio
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

import app.postgres.models  # noqa: F401  (registers every table the deal FKs point at)
from app.config import settings
from app.crm.deal_models import DEAL_STAGES, CrmDeal, CrmDealEvent

DEMO_SOURCE = "Demo seed (synthetic)"

CLIENTS = [
    "Aisha Rahman",
    "Daniel Okafor",
    "Priya Nair",
    "Omar Haddad",
    "Elena Petrova",
    "James Whitfield",
    "Fatima Al Suwaidi",
    "Rohan Mehta",
    "Sofia Marino",
    "Khalid Mansour",
    "Chen Wei",
    "Laura Schmidt",
    "Yusuf Demir",
    "Hannah Clarke",
    "Arjun Kapoor",
    "Mariam Nasser",
    "Lucas Ferreira",
    "Nadia Karim",
    "Thomas Byrne",
    "Leila Farouk",
]
COUNTERPARTIES = [
    "Seller: Al Habtoor family office",
    "Landlord: M. Qureshi",
    "Seller: R. Ivanov",
    "Landlord: Gulf Homes LLC",
    "Seller: S. Patel",
    "Landlord: A. Bin Saeed",
    "",
]
UNITS = {
    "24a0ac0e": [
        "Bloom Towers B-1204",
        "Belgravia III 507",
        "Binghatti Gems 1803",
        "Oxford Residence 2 916",
        "District 12 Villa 41",
        "Ellington Park Villas 7",
    ],
    "b5e5722d": [
        "Marina Gate 2 3105",
        "Cayan Tower 4402",
        "Princess Tower 6210",
        "Marina Promenade Aurora 1102",
        "Silverene A 2507",
        "Botanica Tower 1909",
    ],
}
ORIGINS = [
    "listing",
    "portal",
    "portal",
    "ads",
    "own_contact",
    "owner_outreach",
    "agent_to_agent",
    "renewal",
]


@dataclass
class PlannedDeal:
    agent: str
    team_id: str
    deal_type: str
    unit: str
    client: str
    counterparty: str
    value_aed: int
    origin: str
    status: str  # open | won | lost
    stage_index: int
    created_at: datetime
    # (kind, from_stage, to_stage, at, detail)
    events: list[tuple[str, int | None, int | None, datetime, dict]] = field(default_factory=list)

    @property
    def closed_at(self) -> datetime | None:
        return self.events[-1][3] if self.status != "open" else None

    @property
    def due_date(self) -> date | None:
        if self.status != "open":
            return None
        return (self.created_at + timedelta(days=45 if self.deal_type == "sale" else 21)).date()


def plan(
    members: list[tuple[str, str]], per_agent: int, now: datetime, seed: int = 7
) -> list[PlannedDeal]:
    """members: (team_id, agent user id). Deterministic for a given seed."""
    rng = random.Random(seed)
    planned: list[PlannedDeal] = []
    for team_id, agent in members:
        units = UNITS.get(team_id[:8], UNITS["24a0ac0e"])
        for n in range(per_agent):
            deal_type = "sale" if rng.random() < 0.6 else "rent"
            stages = DEAL_STAGES[deal_type]
            outcome = rng.choices(["open", "won", "lost"], weights=[6, 2, 1])[0]
            created = now - timedelta(days=rng.randint(3, 50), hours=rng.randint(0, 23))
            if outcome == "open":
                target = rng.randint(0, len(stages) - 2)  # the last step closes as won
            elif outcome == "won":
                target = len(stages) - 1
            else:
                target = rng.randint(0, len(stages) - 2)
            value = (
                rng.randrange(900_000, 6_500_000, 25_000)
                if deal_type == "sale"
                else rng.randrange(65_000, 320_000, 5_000)
            )
            deal = PlannedDeal(
                agent=agent,
                team_id=team_id,
                deal_type=deal_type,
                unit=rng.choice(units),
                client=CLIENTS[len(planned) % len(CLIENTS)],
                counterparty=rng.choice(COUNTERPARTIES),
                value_aed=value,
                origin=rng.choice(ORIGINS),
                status=outcome,
                stage_index=target,
                created_at=created,
            )
            # Spread the moves between creation and a recent "last touch" (some within the last day).
            last_touch = now - (
                timedelta(hours=rng.randint(1, 20))
                if n == 0
                else timedelta(days=rng.randint(1, 25))
            )
            last_touch = max(last_touch, created + timedelta(hours=2))
            steps = target + (1 if outcome != "open" else 0)
            span = (last_touch - created) / max(steps, 1)
            deal.events.append(("created", None, 0, created, {}))
            for i in range(target):
                deal.events.append(("stage", i, i + 1, created + span * (i + 1), {}))
            if outcome == "won":
                deal.events.append(("closed", target, None, last_touch, {"outcome": "won"}))
            elif outcome == "lost":
                deal.events.append(
                    (
                        "closed",
                        target,
                        None,
                        last_touch,
                        {
                            "outcome": "lost",
                            "reason": rng.choice(
                                ["Client withdrew", "Finance declined", "Chose another unit"]
                            ),
                        },
                    )
                )
            planned.append(deal)
    return planned


async def _members(db: AsyncSession, org: str) -> list[tuple[str, str]]:
    rows = await db.exec(
        text(
            "select m.team_id, m.user_id from organization_team_members m "
            "join organization_teams t on t.id = m.team_id "
            "where t.organization_id = :o and m.role = 'agent' order by t.name, m.user_id"
        ).bindparams(o=org)
    )
    return [(r[0], r[1]) for r in rows]


async def _reset(db: AsyncSession, org: str) -> int:
    result = await db.exec(
        text("delete from crm_deals where organization_id = :o and origin_source = :s").bindparams(
            o=org, s=DEMO_SOURCE
        )
    )
    return result.rowcount or 0


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--per-agent", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--reset", action="store_true", help="remove the seeded demo deals and stop"
    )
    args = parser.parse_args()

    engine = create_async_engine(str(settings.POSTGRES_URL), pool_pre_ping=True)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as db:
        if args.reset:
            removed = await _reset(db, args.organization_id)
            await db.commit()
            print(f"Removed {removed} demo deals")
            await engine.dispose()
            return

        members = await _members(db, args.organization_id)
        if not members:
            raise SystemExit("No team agents in this organization; add agents to a team first")
        now = datetime.now(timezone.utc)
        planned = plan(members, args.per_agent, now)
        for d in planned:
            print(
                f"{d.team_id[:8]} {d.agent[:8]} {d.deal_type:4} {d.status:4} "
                f"{DEAL_STAGES[d.deal_type][d.stage_index]:<20} AED {d.value_aed:>10,} {d.unit}"
            )
        print(f"{len(planned)} deals for {len(members)} team agents")
        if args.dry_run:
            await engine.dispose()
            return

        # Re-running replaces the previous demo set rather than piling up.
        removed = await _reset(db, args.organization_id)
        for d in planned:
            deal = CrmDeal(
                organization_id=args.organization_id,
                lead_id=None,
                assigned_user_id=d.agent,
                team_id=d.team_id,
                created_by_user_id=d.agent,
                deal_type=d.deal_type,
                unit=d.unit,
                client=d.client,
                counterparty=d.counterparty,
                value_aed=d.value_aed,
                due_date=d.due_date,
                origin=d.origin,
                origin_source=DEMO_SOURCE,
                stage_index=d.stage_index,
                status=d.status,
                created_at=d.created_at,
                updated_at=d.events[-1][3],
                closed_at=d.closed_at,
            )
            db.add(deal)
            await db.flush()
            for kind, from_stage, to_stage, at, detail in d.events:
                db.add(
                    CrmDealEvent(
                        organization_id=args.organization_id,
                        deal_id=deal.id,
                        actor_user_id=d.agent,
                        kind=kind,
                        from_stage=from_stage,
                        to_stage=to_stage,
                        detail=detail,
                        created_at=at,
                    )
                )
        await db.commit()
        print(f"Replaced {removed} earlier demo deals; inserted {len(planned)}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
