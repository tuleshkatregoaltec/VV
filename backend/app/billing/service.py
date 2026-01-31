import stripe
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.config import settings
from app.billing.models import Subscription
from app.organization.models import Organization, OrganizationMembership
from app.core.exceptions import AuthError
from fastapi import HTTPException
from uuid import uuid4

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)


async def sync_stripe_to_postgres(stripe_customer_id: str, db: AsyncSession) -> dict:
    """Idempotent sync from Stripe to Postgres (single source of truth)."""
    try:
        logger.info(f"Syncing Stripe customer {stripe_customer_id}")

        stmt = select(Organization).where(
            Organization.stripe_customer_id == stripe_customer_id
        )
        result = await db.execute(stmt)
        org = result.scalar_one_or_none()

        if not org:
            logger.error(f"No organization found for customer {stripe_customer_id}")
            raise ValueError(
                f"Organization not found for customer {stripe_customer_id}"
            )

        subscriptions = stripe.Subscription.list(
            customer=stripe_customer_id,
            limit=10,
            status="all",
        )

        # Prefer active/trialing subscriptions over canceled
        active_sub = None
        latest_sub = None

        for sub in subscriptions.data:
            if sub.status in ["active", "trialing"]:
                active_sub = sub
                break
            if latest_sub is None or sub.created > latest_sub.created:
                latest_sub = sub

        stripe_sub = active_sub or latest_sub

        if not stripe_sub:
            logger.info(f"No subscription for customer {stripe_customer_id}")
            org.is_active = False
            org.subscription_status = "none"
            await db.commit()
            return {"status": "none", "organization_id": org.id}

        # Find seat item by matching either tier price ID
        seat_item = None
        for item in stripe_sub.items.data:
            if item.price.id in [
                settings.STRIPE_PRICE_ID_TIER1,
                settings.STRIPE_PRICE_ID_TIER2,
            ]:
                seat_item = item
                break

        if not seat_item:
            logger.error(f"No seat item found in subscription {stripe_sub.id}")
            raise ValueError(f"Subscription {stripe_sub.id} missing seat price item")

        seats = seat_item.quantity

        org.subscription_status = stripe_sub.status
        org.is_active = stripe_sub.status in ["active", "trialing"]
        org.max_users = seats

        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_sub.id
        )
        result = await db.execute(stmt)
        subscription = result.scalar_one_or_none()

        if not subscription:
            subscription = Subscription(
                id=str(uuid4()),
                organization_id=org.id,
                stripe_subscription_id=stripe_sub.id,
                stripe_customer_id=stripe_customer_id,
                stripe_price_id=seat_item.price.id,
                status=stripe_sub.status,
                seats=seats,
                current_period_start=datetime.fromtimestamp(
                    stripe_sub.current_period_start, tz=timezone.utc
                ),
                current_period_end=datetime.fromtimestamp(
                    stripe_sub.current_period_end, tz=timezone.utc
                ),
                cancel_at_period_end=stripe_sub.cancel_at_period_end,
            )
            db.add(subscription)
        else:
            subscription.status = stripe_sub.status
            subscription.seats = seats
            subscription.stripe_price_id = seat_item.price.id
            subscription.current_period_start = datetime.fromtimestamp(
                stripe_sub.current_period_start, tz=timezone.utc
            )
            subscription.current_period_end = datetime.fromtimestamp(
                stripe_sub.current_period_end, tz=timezone.utc
            )
            subscription.cancel_at_period_end = stripe_sub.cancel_at_period_end

        await db.commit()

        logger.info(
            f"Synced org {org.id}: status={org.subscription_status}, seats={org.max_users}"
        )

        return {
            "status": org.subscription_status,
            "organization_id": org.id,
            "seats": org.max_users,
        }

    except Exception as e:
        await db.rollback()
        logger.error(f"Sync failed for customer {stripe_customer_id}: {e}")
        raise


async def create_checkout_session(
    user_id: str,
    email: str,
    organization_name: str,
    seats: int,
    first_name: str,
    last_name: str,
    price_tier: str,
    db: AsyncSession,
) -> dict[str, str]:
    """Create org-first checkout session with idempotency."""
    # Check for existing pending/failed org to reuse
    stmt = select(OrganizationMembership).where(
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.role == "owner",
    )
    result = await db.execute(stmt)
    existing_membership = result.scalar_one_or_none()

    org = None
    if existing_membership:
        stmt = select(Organization).where(
            Organization.id == existing_membership.organization_id
        )
        result = await db.execute(stmt)
        existing_org = result.scalar_one_or_none()

        if existing_org and existing_org.subscription_status in ["pending", "failed"]:
            logger.info(f"Reusing existing org {existing_org.id} for user {user_id}")
            org = existing_org
            org.name = organization_name
            org.max_users = seats
            org.subscription_status = "pending"

    if not org:
        org_id = str(uuid4())
        org = Organization(
            id=org_id,
            name=organization_name,
            owner_user_id=user_id,
            subscription_status="pending",
            is_active=False,
            max_users=seats,
            stripe_customer_id=None,
        )
        db.add(org)

        membership = OrganizationMembership(
            organization_id=org.id,
            user_id=user_id,
            role="owner",
        )
        db.add(membership)

    try:
        await db.commit()
        await db.refresh(org)
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to create organization: {e}")
        raise HTTPException(500, f"Failed to create organization: {str(e)}")

    customer_id = org.stripe_customer_id

    if not customer_id:
        try:
            customer = stripe.Customer.create(
                email=email,
                name=f"{first_name} {last_name}",
                metadata={
                    "organization_id": org.id,
                    "owner_user_id": user_id,
                    "organization_name": organization_name,
                },
            )
            customer_id = customer.id
        except Exception as e:
            logger.error(f"Stripe customer creation failed for org {org.id}: {e}")
            org.subscription_status = "failed"
            await db.commit()
            raise HTTPException(500, f"Failed to create Stripe customer: {str(e)}")

        org.stripe_customer_id = customer_id

        try:
            await db.commit()
            await db.refresh(org)
        except Exception as e:
            await db.rollback()
            try:
                stripe.Customer.delete(customer_id)
            except:
                pass
            logger.error(f"Failed to link Stripe customer: {e}")
            raise HTTPException(500, f"Failed to link Stripe customer: {str(e)}")

    # Use the price tier selected by the user
    price_id = (
        settings.STRIPE_PRICE_ID_TIER1
        if price_tier == "tier1"
        else settings.STRIPE_PRICE_ID_TIER2
    )

    try:
        idempotency_key = (
            f"checkout_{org.id}_{int(datetime.now(timezone.utc).timestamp())}"
        )

        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[
                {
                    "price": price_id,
                    "quantity": seats,
                }
            ],
            success_url=f"{settings.FRONTEND_SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=settings.FRONTEND_CANCEL_URL,
            idempotency_key=idempotency_key,
        )
    except Exception as e:
        logger.error(f"Checkout session creation failed for org {org.id}: {e}")
        raise HTTPException(500, f"Failed to create checkout session: {str(e)}")

    return {
        "checkout_url": checkout_session.url or "",
        "session_id": checkout_session.id or "",
        "organization_id": org.id,
    }


async def sync_after_checkout(session_id: str, user_id: str, db: AsyncSession) -> dict:
    """Verify checkout session and sync subscription from Stripe."""
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception as e:
        logger.error(f"Failed to retrieve session {session_id}: {e}")
        raise HTTPException(400, f"Invalid session: {str(e)}")

    if session.status != "complete":
        raise HTTPException(400, f"Session not complete: {session.status}")

    customer_id = session.customer
    if not customer_id:
        raise HTTPException(400, "No customer in session")

    stmt = select(Organization).where(Organization.stripe_customer_id == customer_id)
    result = await db.execute(stmt)
    org = result.scalar_one_or_none()

    if not org:
        raise HTTPException(404, "Organization not found for session")

    # Verify user is owner
    is_owner = False

    if org.owner_user_id == user_id:
        is_owner = True
    else:
        stmt = select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.role == "owner",
        )
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            is_owner = True

    if not is_owner:
        raise HTTPException(403, "Not authorized for this organization")

    result = await sync_stripe_to_postgres(customer_id, db)

    return result


async def get_subscription_by_org(
    organization_id: str, db: AsyncSession
) -> Optional[Subscription]:
    """Get organization subscription."""
    stmt = select(Subscription).where(Subscription.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def cancel_subscription(subscription_id: str, at_period_end: bool = True) -> None:
    """Cancel subscription in Stripe."""
    if at_period_end:
        stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True,
        )
    else:
        stripe.Subscription.cancel(subscription_id)


async def get_customer_portal_url(customer_id: str, return_url: str) -> str:
    """Generate Stripe Customer Portal URL."""
    portal_session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return portal_session.url


def is_subscription_active(subscription: Subscription) -> bool:
    """Check if subscription grants access (status=active and not expired)."""
    now = datetime.now(timezone.utc)

    if subscription.status == "past_due":
        return False

    if subscription.status != "active":
        return False

    return now < subscription.current_period_end


def can_access_product(subscription: Optional[Subscription]) -> bool:
    """Determine if user can access product features."""
    if subscription is None:
        return False
    return is_subscription_active(subscription)


def get_subscription_error(subscription: Optional[Subscription]) -> HTTPException:
    """Return appropriate error for subscription state."""
    if subscription is None:
        return AuthError.subscription_required()

    if subscription.status == "past_due":
        return AuthError.subscription_past_due()

    # Default to subscription required for all other inactive states
    return AuthError.subscription_required()
