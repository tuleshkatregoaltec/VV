from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from workos import WorkOSClient
from typing import Dict, Optional
from sqlmodel import Session, func, select
from datetime import datetime, timezone

from backend.app.services.organisation_service import (
    validate_organisation_access, 
    OrganisationError
)
from backend.app.db.models import User, Organisation
from backend.app.config import settings

workos = WorkOSClient(
    api_key=settings.WORKOS_API_KEY, 
    client_id=settings.WORKOS_CLIENT_ID
)

async def get_authorization_url() -> str:
    """Generate WorkOS authorization URL for login via AuthKit."""
    authorization_url = workos.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=settings.WORKOS_REDIRECT_URI,
    )
    return authorization_url

async def handle_callback(request: Request, code: str, session: Session) -> RedirectResponse:
    try:
        # Step 1: Authenticate user and get profile
        auth_response = workos.user_management.authenticate_with_code(code=code)
        user = auth_response.user

        # Step 2: List all active organization memberships for user
        memberships_response = workos.user_management.list_organization_memberships(
            user_id=user.id,
            statuses=["active"]  # only active memberships
        )
        memberships = memberships_response.data

        if not memberships:
            # User has no active org memberships - block access
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/no-org")

        # Step 3: Pick primary organization membership (first active membership)
        primary_membership = memberships[0]
        workos_org_id = primary_membership.organization_id

        # Step 4: Lookup local organisation by WorkOS org ID
        organisation = session.get(Organisation, workos_org_id)
        if not organisation:
            # Organization not onboarded locally
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/no-org")

        # Step 5: Check if user exists locally
        existing_user = session.get(User, user.id)
        if existing_user:
            if not existing_user.is_active:
                return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/deactivated")

            # Update last login and org linkage if needed
            existing_user.last_login = datetime.now(timezone.utc)
            if existing_user.organisation_id != organisation.id:
                existing_user.organisation_id = organisation.id
            session.commit()
            session.refresh(existing_user)

            # Set session
            request.session["user"] = {
                "id": existing_user.id,
                "email": existing_user.email,
                "first_name": existing_user.first_name,
                "last_name": existing_user.last_name,
                "organisation_id": existing_user.organisation_id,
                "organisation_name": organisation.name,
            }
            request.session["access_token"] = auth_response.access_token
            request.session["refresh_token"] = auth_response.refresh_token

            return RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard")

        # Step 6: New user - enforce organisation user limit
        active_user_count = session.exec(
            select(func.count()).select_from(User).where(
                User.organisation_id == organisation.id,
                User.is_active == True,
            )
        ).one()
        is_active = active_user_count < organisation.max_users

        # Create new user locally
        new_user = User(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            organisation_id=organisation.id,
            is_active=is_active,
            created_at=datetime.now(timezone.utc),
            last_login=datetime.now(timezone.utc),
        )
        session.add(new_user)
        session.commit()
        session.refresh(new_user)

        if not is_active:
            # Redirect new user over limit to deactivated page
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/deactivated")

        # Set session for active user
        request.session["user"] = {
            "id": new_user.id,
            "email": new_user.email,
            "first_name": new_user.first_name,
            "last_name": new_user.last_name,
            "organisation_id": organisation.id,
            "organisation_name": organisation.name,
        }
        request.session["access_token"] = auth_response.access_token
        request.session["refresh_token"] = auth_response.refresh_token

        return RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard")

    except OrganisationError as e:
        # Log organisation-specific errors and show deactivated page
        print(f"Organisation error: {e}")
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/no-org")

    except Exception as e:
        # Log general errors and return HTTP 400
        print(f"Auth error: {e}")
        raise HTTPException(status_code=400, detail="Authentication failed")

async def logout_user(request: Request) -> RedirectResponse:
    """Clear user session"""
    request.session.clear()
    return RedirectResponse(url=settings.FRONTEND_URL)

async def get_current_user(request: Request) -> Dict:
    """Get current authenticated user from session"""
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

async def get_session_info(request: Request) -> Optional[Dict]:
    """Get session info (returns None if not authenticated)"""
    user = request.session.get("user")
    access_token = request.session.get("access_token")
    
    if not user:
        return None
    
    return {"user": user, "access_token": access_token, "authenticated": True}
