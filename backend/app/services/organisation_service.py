from sqlmodel import Session, select, func
from typing import Optional
from backend.app.db.models import Organisation, User

class OrganisationError(Exception):
    """Custom exception for Organisation-related errors"""
    pass

def extract_domain(email: str) -> str:
    return email.split('@')[1].lower()

def get_organisation_by_domain(session: Session, email: str) -> Optional[Organisation]:
    """Get organisation by email domain"""
    domain = extract_domain(email)
    statement = select(Organisation).where(Organisation.email_domain == domain)
    return session.exec(statement).first()

def validate_organisation_access(session: Session, email: str) -> Organisation:
    """
    Validate that user can join organisation.
    Raises OrganisationError if:
    - organisation doesn't exist
    - organisation is inactive
    - user limit reached
    """
    organisation = get_organisation_by_domain(session, email)
    
    if not organisation:
        domain = extract_domain(email)
        raise OrganisationError(
            f"No organisation found for domain '{domain}'. "
            "Please contact support to set up your organisation."
        )
    
    if not organisation.is_active:
        raise OrganisationError(
            "Your organisation account is inactive. Please contact support."
        )
    
    # Count active users in organisation
    statement = select(func.count()).select_from(User).where(
        User.organisation_id == organisation.id,
        User.is_active == True
    )
    current_user_count = session.exec(statement).one()
    
    if current_user_count >= organisation.max_users:
        raise OrganisationError(
            f"User limit reached for your organisation ({organisation.max_users} users). "
            "Please contact support to increase your user limit."
        )
    
    return organisation

def get_organisation_user_count(session: Session, organisation_id: int) -> dict:
    """Get user count statistics for an organisation"""
    statement = select(func.count()).select_from(User).where(
        User.organisation_id == organisation_id,
        User.is_active == True
    )
    active_count = session.exec(statement).one()
    
    organisation: Organisation | None = session.get(Organisation, organisation_id)
    
    if not organisation:
        raise OrganisationError(f"Organisation does not exist")

    return {
        "active_users": active_count,
        "max_users": organisation.max_users,
        "available_slots": organisation.max_users - active_count
    }
