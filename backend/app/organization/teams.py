"""Teams, supervision and organization administration.

Owners are always organization administrators; an owner can make other members administrators.
A team's supervisors are its managers. Membership rows are keyed to the organization in the
database, so a team never holds someone from another organization.
"""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.service import get_user_by_id
from app.organization import repository
from app.organization.models import (
    OperationSuccessResponse,
    OrganizationMembership,
    OrganizationTeam,
    OrganizationTeamMember,
    TeamMemberResponse,
    TeamMembersUpdateRequest,
    TeamPersonResponse,
    TeamResponse,
    TeamsResponse,
    TeamWriteRequest,
)


def is_organization_admin(membership: OrganizationMembership | None) -> bool:
    return bool(membership) and (membership.role == "owner" or membership.organization_admin)


async def organization_people(db: AsyncSession, org_id: str) -> dict[str, TeamPersonResponse]:
    """Every member of the organization with the name the identity provider holds."""
    people = {}
    for membership in await repository.list_memberships(db, org_id):
        user = await get_user_by_id(membership.user_id)
        name = f"{user.first_name} {user.last_name}".strip() if user else ""
        people[membership.user_id] = TeamPersonResponse(
            user_id=membership.user_id,
            name=name or (user.email if user else "Former member"),
            email=user.email if user else "",
            role=membership.role,
            organization_admin=is_organization_admin(membership),
        )
    return people


async def list_team_memberships(db: AsyncSession, org_id: str) -> list[OrganizationTeamMember]:
    return list(await repository.list_team_members(db, org_id))


async def list_org_teams(db: AsyncSession, org_id: str) -> list[OrganizationTeam]:
    return list(await repository.list_teams(db, org_id))


async def lock_destination(db: AsyncSession, org_id: str, user_id: str, team_ids) -> bool:
    """True when the user is still in one of these teams; holds that row until commit."""
    return bool(await repository.lock_team_membership(db, org_id, user_id, team_ids))


async def lock_membership(db: AsyncSession, org_id: str, user_id: str) -> bool:
    """True when the user is still a member; holds that row until commit."""
    return await repository.lock_membership_in_org(db, org_id, user_id) is not None


async def list_teams(db: AsyncSession, org_id: str) -> TeamsResponse:
    people = await organization_people(db, org_id)
    members_by_team: dict[str, list[TeamMemberResponse]] = {}
    for row in await repository.list_team_members(db, org_id):
        person = people.get(row.user_id)
        members_by_team.setdefault(row.team_id, []).append(
            TeamMemberResponse(
                user_id=row.user_id,
                name=person.name if person else row.user_id,
                email=person.email if person else "",
                role=row.role,  # type: ignore[arg-type]
            )
        )
    teams = [
        TeamResponse(
            id=team.id,
            name=team.name,
            members=sorted(members_by_team.get(team.id, []), key=lambda m: m.name.casefold()),
            created_at=team.created_at,
            updated_at=team.updated_at,
        )
        for team in await repository.list_teams(db, org_id)
    ]
    return TeamsResponse(
        teams=teams, people=sorted(people.values(), key=lambda p: p.name.casefold())
    )


async def _team_or_404(db: AsyncSession, org_id: str, team_id: str) -> OrganizationTeam:
    team = await repository.get_team_in_org(db, org_id, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def _commit_name(db: AsyncSession, team: OrganizationTeam) -> None:
    repository.save_team(db, team)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A team with this name exists") from exc


async def create_team(db: AsyncSession, org_id: str, request: TeamWriteRequest) -> TeamsResponse:
    await _commit_name(db, OrganizationTeam(organization_id=org_id, name=request.name.strip()))
    return await list_teams(db, org_id)


async def rename_team(
    db: AsyncSession, org_id: str, team_id: str, request: TeamWriteRequest
) -> TeamsResponse:
    team = await _team_or_404(db, org_id, team_id)
    team.name = request.name.strip()
    team.updated_at = datetime.now(timezone.utc)
    await _commit_name(db, team)
    return await list_teams(db, org_id)


async def delete_team(db: AsyncSession, org_id: str, team_id: str) -> OperationSuccessResponse:
    team = await _team_or_404(db, org_id, team_id)
    await repository.delete_team(db, team)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This team still has routing rules or leads. Move or delete them first.",
        ) from exc
    return OperationSuccessResponse(success=True)


async def replace_team_members(
    db: AsyncSession, org_id: str, team_id: str, request: TeamMembersUpdateRequest
) -> TeamsResponse:
    team = await _team_or_404(db, org_id, team_id)
    user_ids = [member.user_id for member in request.members]
    if len(set(user_ids)) != len(user_ids):
        raise HTTPException(status_code=422, detail="A person is listed twice")
    members = {row.user_id for row in await repository.list_memberships(db, org_id)}
    if outside := [user_id for user_id in user_ids if user_id not in members]:
        raise HTTPException(
            status_code=422, detail=f"Not a member of this organization: {', '.join(outside)}"
        )
    await repository.delete_team_members(db, team.id)
    for member in request.members:
        repository.save_team(
            db,
            OrganizationTeamMember(
                team_id=team.id, organization_id=org_id, user_id=member.user_id, role=member.role
            ),
        )
    team.updated_at = datetime.now(timezone.utc)
    repository.save_team(db, team)
    await db.commit()
    return await list_teams(db, org_id)


async def set_organization_admin(
    db: AsyncSession, org_id: str, user_id: str, enabled: bool
) -> OperationSuccessResponse:
    membership = await repository.get_membership_in_org(db, org_id, user_id)
    if not membership:
        raise HTTPException(status_code=404, detail="User not found in organization")
    if membership.role == "owner":
        raise HTTPException(status_code=400, detail="Owners always administer the organization")
    membership.organization_admin = enabled
    membership.updated_at = datetime.now(timezone.utc)
    repository.save_membership(db, membership)
    await db.commit()
    return OperationSuccessResponse(success=True)


async def get_membership(
    db: AsyncSession, org_id: str, user_id: str
) -> OrganizationMembership | None:
    return await repository.get_membership_in_org(db, org_id, user_id)
