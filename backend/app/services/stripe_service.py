import stripe
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models.subscriptions import Subscription
from app.db.models.auth import Organization

# Configure Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY


def get_price_for_seats(seats: int) -> tuple[str, int]:
    """
    Determine Stripe price ID and unit amount based on seat count.

    Returns:
        tuple[str, int]: (price_id, unit_amount in fils)
    """
    if seats < 1:
        raise ValueError("Seat count must be at least 1")
    elif seats <= 5:
        # Tier 1: 990 AED per seat
        return (settings.STRIPE_PRICE_ID_TIER1, 99000)
    elif seats <= 10:
        # Tier 2: 890 AED per seat
        return (settings.STRIPE_PRICE_ID_TIER2, 89000)
    else:
        # Enterprise: Contact sales required
        raise ValueError(
            f"Seat count {seats} exceeds self-service limit. Contact {settings.ENTERPRISE_CONTACT_EMAIL} for enterprise plans."
        )


async def create_checkout_session(
    user_id: str, email: str, organization_name: str, seats: int, db: AsyncSession
) -> dict[str, str]:
    """
    Create a Stripe Checkout session for organization subscription.

    Args:
        user_id: Supabase user ID
        email: User email for Stripe customer
        organization_name: Name of organization to create
        seats: Number of seats to purchase
        db: Database session

    Returns:
        dict with checkout_url and session_id
    """
    # Validate seats and get price
    price_id, unit_amount = get_price_for_seats(seats)

    # Create organization with pending_payment status
    org_id = str(uuid.uuid4())

    # Create Stripe checkout session first
    checkout_session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[
            {
                "price": price_id,
                "quantity": seats,
            }
        ],
        success_url=f"{settings.FRONTEND_SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=settings.FRONTEND_CANCEL_URL,
        customer_email=email,
        metadata={
            "user_id": user_id,
            "organization_id": org_id,
            "organization_name": organization_name,
            "seats": str(seats),
            "tier": "tier1" if seats <= 5 else "tier2",
        },
        subscription_data={
            "metadata": {
                "organization_id": org_id,
                "organization_name": organization_name,
            }
        },
    )

    # Create organization with pending_payment status
    organization = Organization(
        id=org_id,
        name=organization_name,
        max_users=seats,
        is_active=False,  # Not active until payment completes
        status="pending_payment",
        stripe_checkout_session_id=checkout_session.id,
        organization_admin_id=user_id,  # Set creator as admin
        users=[user_id],  # Add creator as first user
    )
    db.add(organization)
    await db.commit()

    return {
        "checkout_url": checkout_session.url,
        "session_id": checkout_session.id,
    }


async def handle_checkout_completed(session_id: str, db: AsyncSession) -> str:
    """
    Handle successful checkout completion from Stripe webhook.

    Updates organization status and creates subscription record after payment.

    Args:
        session_id: Stripe checkout session ID
        db: Database session

    Returns:
        organization_id: Updated organization ID
    """
    # Retrieve organization by checkout session ID
    stmt = select(Organization).where(
        Organization.stripe_checkout_session_id == session_id
    )
    result = await db.execute(stmt)
    organization = result.scalar_one_or_none()

    if not organization:
        raise ValueError(f"No organization found for session {session_id}")

    if organization.status == "active":
        # Already processed (webhook idempotency)
        return organization.id

    # Retrieve Stripe session details
    checkout_session = stripe.checkout.Session.retrieve(
        session_id, expand=["subscription", "customer"]
    )

    if checkout_session.payment_status != "paid":
        raise ValueError(f"Payment not completed for session {session_id}")

    subscription = checkout_session.subscription
    customer = checkout_session.customer

    # Update organization to active
    organization.status = "active"
    organization.is_active = True
    organization.stripe_customer_id = (
        customer.id if isinstance(customer, stripe.Customer) else customer
    )

    # Create subscription record
    subscription_id = str(uuid.uuid4())
    subscription_record = Subscription(
        id=subscription_id,
        organization_id=organization.id,
        stripe_subscription_id=(
            subscription.id
            if isinstance(subscription, stripe.Subscription)
            else subscription
        ),
        stripe_customer_id=(
            customer.id if isinstance(customer, stripe.Customer) else customer
        ),
        stripe_price_id=checkout_session.metadata.get("tier", "tier1"),
        status="active",
        seats=organization.max_users,
        current_period_start=datetime.fromtimestamp(
            subscription.current_period_start
            if isinstance(subscription, stripe.Subscription)
            else checkout_session.created,
            tz=timezone.utc,
        ),
        current_period_end=datetime.fromtimestamp(
            subscription.current_period_end
            if isinstance(subscription, stripe.Subscription)
            else checkout_session.created + 2592000,  # ~30 days
            tz=timezone.utc,
        ),
    )

    # Link organization to subscription
    organization.subscription_id = subscription_id

    # Save to database
    db.add(subscription_record)
    await db.commit()

    return organization.id


async def get_subscription_by_org(
    organization_id: str, db: AsyncSession
) -> Optional[Subscription]:
    """Get subscription for an organization"""
    stmt = select(Subscription).where(Subscription.organization_id == organization_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def handle_subscription_updated(
    stripe_subscription_id: str, db: AsyncSession
) -> Optional[int]:
    """
    Handle subscription update from Stripe webhook.

    Updates seats and checks for excess users.

    Args:
        stripe_subscription_id: Stripe subscription ID
        db: Database session

    Returns:
        Number of excess users if seats were reduced, None otherwise
    """
    # Retrieve subscription from database
    stmt = select(Subscription).where(
        Subscription.stripe_subscription_id == stripe_subscription_id
    )
    result = await db.execute(stmt)
    subscription = result.scalar_one_or_none()

    if not subscription:
        raise ValueError(
            f"No subscription found for Stripe ID {stripe_subscription_id}"
        )

    # Retrieve updated subscription from Stripe
    stripe_subscription = stripe.Subscription.retrieve(stripe_subscription_id)

    # Extract new seat count from quantity
    new_seats = stripe_subscription["items"]["data"][0]["quantity"]
    old_seats = subscription.seats

    # Update subscription record
    subscription.seats = new_seats
    subscription.status = stripe_subscription.status
    subscription.current_period_start = datetime.fromtimestamp(
        stripe_subscription.current_period_start, tz=timezone.utc
    )
    subscription.current_period_end = datetime.fromtimestamp(
        stripe_subscription.current_period_end, tz=timezone.utc
    )
    subscription.cancel_at_period_end = stripe_subscription.cancel_at_period_end

    # Update price_id if tier changed
    new_price_id = stripe_subscription["items"]["data"][0]["price"]["id"]
    subscription.stripe_price_id = new_price_id

    # Update organization max_users
    stmt = select(Organization).where(Organization.id == subscription.organization_id)
    result = await db.execute(stmt)
    organization = result.scalar_one()
    organization.max_users = new_seats

    await db.commit()

    # Check if we have excess users
    active_user_count = len(organization.users)
    if active_user_count > new_seats:
        return active_user_count - new_seats

    return None


async def cancel_subscription(subscription_id: str, at_period_end: bool = True) -> None:
    """
    Cancel a subscription in Stripe.

    Args:
        subscription_id: Stripe subscription ID (not database ID)
        at_period_end: If True, cancel at end of billing period
    """
    if at_period_end:
        stripe.Subscription.modify(
            subscription_id,
            cancel_at_period_end=True,
        )
    else:
        stripe.Subscription.cancel(subscription_id)


async def get_customer_portal_url(customer_id: str, return_url: str) -> str:
    """
    Generate Stripe Customer Portal session URL.

    Args:
        customer_id: Stripe customer ID
        return_url: URL to return to after portal session

    Returns:
        Customer Portal URL
    """
    portal_session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return portal_session.url
