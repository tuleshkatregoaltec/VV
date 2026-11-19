"""An agency with teams, for testing that assistant access follows CRM roles.

Owner (organization admin); Nadia supervises North (Omar, Sara); Karim supervises South (Lina).
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry
from app.organization.models import (
    Organization,
    OrganizationMembership,
    OrganizationTeam,
    OrganizationTeamMember,
)


async def agency(db) -> dict[str, str]:
    org = str(uuid4())
    db.add(Organization(id=org, name="Agency", subscription_status="active"))
    await db.flush()
    ids = {"org": org}
    for name in ("owner", "nadia", "omar", "sara", "karim", "lina"):
        ids[name] = f"{name}-{uuid4().hex[:6]}"
        role = "owner" if name == "owner" else "member"
        db.add(OrganizationMembership(organization_id=org, user_id=ids[name], role=role))
    await db.flush()
    for team, members in (
        ("north", {"nadia": "supervisor", "omar": "agent", "sara": "agent"}),
        ("south", {"karim": "supervisor", "lina": "agent"}),
    ):
        row = OrganizationTeam(organization_id=org, name=team.title())
        db.add(row)
        await db.flush()
        ids[team] = row.id
        for person, role in members.items():
            db.add(
                OrganizationTeamMember(
                    team_id=row.id, organization_id=org, user_id=ids[person], role=role
                )
            )
    await db.commit()
    return ids


async def lead(
    db,
    ids,
    name: str,
    *,
    team: str | None,
    assignee: str | None,
    creator: str | None = None,
    pooled: bool = False,
    status: str = "new",
) -> SimpleNamespace:
    """A lead owned by `team` ("north"/"south"/None) and assigned to a person name or None."""
    now = datetime.now(UTC)
    contact = CrmInboundContact(
        organization_id=ids["org"],
        full_name=name,
        phone="+971500000009",
        email=f"{name.lower()}@example.test",
        created_at=now,
        updated_at=now,
    )
    db.add(contact)
    await db.flush()
    enquiry = CrmInboundEnquiry(
        organization_id=ids["org"],
        contact_id=contact.id,
        created_by_user_id=ids[creator or assignee or "owner"],
        assigned_user_id=ids[assignee] if assignee else None,
        team_id=ids[team] if team else None,
        pool_released_at=now if pooled else None,
        intent="buy",
        status=status,
        enquiry_date=now,
        created_at=now,
        updated_at=now,
    )
    db.add(enquiry)
    await db.commit()
    # Plain values: service commits expire ORM rows the test still holds.
    return SimpleNamespace(
        id=enquiry.id, team_id=enquiry.team_id, assignment_revision=enquiry.assignment_revision
    )
