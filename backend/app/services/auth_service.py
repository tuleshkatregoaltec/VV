from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from workos import WorkOSClient
from typing import Dict, Optional
from sqlmodel import Session, func, select
from datetime import datetime, timezone

from backend.app.services.organisation_service import (
    validate_organisation_access,
    OrganisationError,
)
from backend.app.db.models import User, Organisation
from backend.app.config import settings

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
    request: Request, code: str, session: Session
) -> RedirectResponse:
    try:
        auth_response = workos.user_management.authenticate_with_code(code=code)
        user = auth_response.user

        try:
            organisation = validate_organisation_access(session, user.email)
        except OrganisationError as e:
            print(f"Organisation validation error: {e}")
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/no-org")

        existing_user = session.get(User, user.id)
        if existing_user:
            if not existing_user.is_active:
                return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/deactivated")

            existing_user.last_login = datetime.now(timezone.utc)
            if existing_user.organisation_id != organisation.id:
                existing_user.organisation_id = organisation.id
            session.commit()
            session.refresh(existing_user)

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

        active_user_count = session.exec(
            select(func.count())
            .select_from(User)
            .where(
                User.organisation_id == organisation.id,
                User.is_active == True,
            )
        ).one()
        is_active = active_user_count < organisation.max_users

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
            return RedirectResponse(url=f"{settings.FRONTEND_URL}/auth/deactivated")

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

    except Exception as e:
        print(f"Auth error: {e}")
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
