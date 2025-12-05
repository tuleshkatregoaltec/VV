from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from workos import WorkOSClient
from typing import Dict, Optional
from sqlmodel.ext.asyncio.session import AsyncSession
from datetime import datetime, timezone
import asyncio
import logging

from backend.app.services.organization_service import (
    get_organization_by_id,
    get_organization_by_domain,
    get_active_user_count,
)
from backend.app.db.models import User
from backend.app.config import settings

logger = logging.getLogger(__name__)

workos = WorkOSClient(
    api_key=settings.WORKOS_API_KEY, client_id=settings.WORKOS_CLIENT_ID
)


async def get_authorization_url() -> str:
    authorization_url = workos.user_management.get_authorization_url(
        provider="authkit",
        redirect_uri=settings.WORKOS_REDIRECT_URI,
    )
    return authorization_url


async def handle_callback(
    request: Request, code: str, session: AsyncSession
) -> RedirectResponse:
    """Handle OAuth callback from WorkOS AuthKit"""
    try:
        # Step 1: Authenticate with WorkOS and get user profile (sync SDK call)
        auth_response = await asyncio.to_thread(
            workos.user_management.authenticate_with_code, code=code
        )
        workos_user = auth_response.user

        # Step 2: Get user's active organization memberships (sync SDK call)
        memberships_response = await asyncio.to_thread(
            workos.user_management.list_organization_memberships,
            user_id=workos_user.id,
            statuses=["active"],
        )
        memberships = memberships_response.data

        organization = None
        has_workos_membership = False

        if memberships:
            # User has org memberships - use primary organization
            primary_membership = memberships[0]
            workos_org_id = primary_membership.organization_id
            organization = await get_organization_by_id(session, workos_org_id)
            if organization:
                has_workos_membership = True

        # Fallback: match by email domain if no membership or org not found locally
        if not organization:
            email_domain = workos_user.email.split("@")[1].lower()
            organization = await get_organization_by_domain(session, email_domain)

            if not organization:
                # No org found by membership or domain
                return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/no-org")

        # If user matched by domain but has no WorkOS membership, create one
        if not has_workos_membership:
            try:
                await asyncio.to_thread(
                    workos.user_management.create_organization_membership,
                    user_id=workos_user.id,
                    organization_id=organization.id,
                )
            except Exception as e:
                # Log but don't fail - user can still proceed with domain-based auth
                logger.warning(
                    f"Failed to create WorkOS org membership for user {workos_user.id}: {e}"
                )

        # Step 5: Check if organization is active
        if not organization.is_active:
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/deactivated")

        # Step 6: Check if user exists in local DB
        existing_user = await session.get(User, workos_user.id)

        if existing_user:
            # EXISTING USER - update org if needed and check status
            if existing_user.organization_id != organization.id:
                # User's org has changed or was previously unassigned
                existing_user.organization_id = organization.id

            existing_user.last_login = datetime.now(timezone.utc)
            existing_user.updated_at = datetime.now(timezone.utc)
            session.add(existing_user)
            await session.commit()
            await session.refresh(existing_user)

            # Check if user is active
            if not existing_user.is_active:
                return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/deactivated")

            # Set session and redirect to dashboard
            request.session["user"] = {
                "id": existing_user.id,
                "email": existing_user.email,
                "first_name": existing_user.first_name,
                "last_name": existing_user.last_name,
                "organization_id": existing_user.organization_id,
                "organization_name": organization.name,
            }
            request.session["access_token"] = auth_response.access_token
            request.session["refresh_token"] = auth_response.refresh_token

            return RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard")

        # Step 7: NEW USER - check user limit and create
        active_user_count = await get_active_user_count(session, organization.id)

        # Determine if user should be active based on org limit
        is_active = active_user_count < organization.max_users

        # Create new user
        new_user = User(
            id=workos_user.id,
            email=workos_user.email,
            first_name=workos_user.first_name,
            last_name=workos_user.last_name,
            organization_id=organization.id,
            is_active=is_active,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            last_login=datetime.now(timezone.utc),
        )
        session.add(new_user)
        await session.commit()
        await session.refresh(new_user)

        # If user is not active (over limit), redirect to deactivated
        if not is_active:
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/deactivated")

        # Set session for new active user
        request.session["user"] = {
            "id": new_user.id,
            "email": new_user.email,
            "first_name": new_user.first_name,
            "last_name": new_user.last_name,
            "organization_id": organization.id,
            "organization_name": organization.name,
        }
        request.session["access_token"] = auth_response.access_token
        request.session["refresh_token"] = auth_response.refresh_token

        return RedirectResponse(url=f"{settings.FRONTEND_URL}/dashboard")

    except Exception:
        logger.exception("Authentication error")
        raise HTTPException(status_code=400, detail="Authentication failed")


async def logout_user(request: Request) -> RedirectResponse:
    """Clear user session"""
    request.session.clear()
    return RedirectResponse(url=settings.FRONTEND_URL)


async def get_current_user(request: Request) -> Dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def get_session_info(request: Request) -> Optional[Dict]:
    user = request.session.get("user")
    access_token = request.session.get("access_token")

    if not user:
        return None

    return {"user": user, "access_token": access_token, "authenticated": True}
