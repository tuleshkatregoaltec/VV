from typing import Optional
from pydantic import BaseModel
from fastapi import HTTPException


class ErrorDetail(BaseModel):
    """Structured error response."""
    code: str
    message: str
    action: Optional[str] = None
    redirect_url: Optional[str] = None


class AuthError:
    """Standard auth error codes and responses."""

    @staticmethod
    def subscription_required(billing_url: str = "/settings/organization") -> HTTPException:
        return HTTPException(
            status_code=402,
            detail=ErrorDetail(
                code="SUBSCRIPTION_REQUIRED",
                message="Active subscription required to access this resource.",
                action="REDIRECT_BILLING",
                redirect_url=billing_url
            ).model_dump()
        )

    @staticmethod
    def subscription_past_due(billing_url: str = "/settings/organization") -> HTTPException:
        return HTTPException(
            status_code=402,
            detail=ErrorDetail(
                code="SUBSCRIPTION_PAST_DUE",
                message="Payment method declined. Please update your billing information.",
                action="REDIRECT_BILLING",
                redirect_url=billing_url
            ).model_dump()
        )

    @staticmethod
    def no_org_membership() -> HTTPException:
        return HTTPException(
            status_code=403,
            detail=ErrorDetail(
                code="NO_ORG_MEMBERSHIP",
                message="You must join an organization to access this resource.",
                action="REDIRECT_ONBOARDING",
                redirect_url="/onboarding/organization-setup"
            ).model_dump()
        )

    @staticmethod
    def org_disabled() -> HTTPException:
        return HTTPException(
            status_code=403,
            detail=ErrorDetail(
                code="ORG_DISABLED",
                message="Your organization has been deactivated. Please contact support.",
                action="CONTACT_SUPPORT"
            ).model_dump()
        )

    @staticmethod
    def owner_required() -> HTTPException:
        return HTTPException(
            status_code=403,
            detail=ErrorDetail(
                code="OWNER_REQUIRED",
                message="Organization owner access required for this action."
            ).model_dump()
        )
