from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import AuthContext


@dataclass
class AssistantDeps:
    """What every assistant tool may use. The scope comes only from the signed-in AuthContext;
    no tool takes an organisation or user from the model."""

    db: AsyncSession
    user_id: str
    organization_id: str
    organization_name: str
    role: str
    organization: object
    conversation_id: int | None = None

    @classmethod
    def from_auth(cls, context: AuthContext, db: AsyncSession) -> "AssistantDeps":
        return cls(
            db=db,
            user_id=str(context.user.id),
            organization_id=str(context.organization.id),
            organization_name=context.organization.name,
            role=context.membership.role,
            organization=context.organization,
        )
