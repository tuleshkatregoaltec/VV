import stripe
import logging
from fastapi import APIRouter, Request, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.config import settings
from app.db.session import get_db_session
from app.services.stripe_service import (
    handle_checkout_completed,
    handle_subscription_updated,
)
from app.db.models.auth import Organization

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/stripe")
async def stripe_webhook(request: Request):
    """
    Handle Stripe webhook events.

    No authentication required - validated by webhook signature.

    Events handled:
    - checkout.session.completed: Create organization after payment
    - customer.subscription.updated: Handle seat changes, tier switches
    - customer.subscription.deleted: Deactivate organization at period end
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        # Invalid payload
        logger.error("Invalid webhook payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.SignatureVerificationError as e:
        # Invalid signature
        logger.error("Invalid webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Get database session
    async for db in get_db_session():
        try:
            # Handle the event
            if event["type"] == "checkout.session.completed":
                session = event["data"]["object"]
                await _handle_checkout_completed(session, db)

            elif event["type"] == "customer.subscription.updated":
                subscription = event["data"]["object"]
                await _handle_subscription_updated(subscription, db)

            elif event["type"] == "customer.subscription.deleted":
                subscription = event["data"]["object"]
                await _handle_subscription_deleted(subscription, db)

            else:
                logger.info(f"Unhandled event type: {event['type']}")

        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success"}


async def _handle_checkout_completed(session: dict, db: AsyncSession):
    """Handle checkout.session.completed event"""
    try:
        organization_id = await handle_checkout_completed(session["id"], db)
        logger.info(
            f"Organization created successfully: {organization_id} for session {session['id']}"
        )
    except Exception as e:
        logger.error(f"Failed to handle checkout completion: {e}")
        raise


async def _handle_subscription_updated(subscription: dict, db: AsyncSession):
    """Handle customer.subscription.updated event"""
    try:
        excess_users = await handle_subscription_updated(subscription["id"], db)
        if excess_users:
            logger.warning(
                f"Subscription {subscription['id']} has {excess_users} excess users after seat reduction"
            )
        else:
            logger.info(f"Subscription {subscription['id']} updated successfully")
    except Exception as e:
        logger.error(f"Failed to handle subscription update: {e}")
        raise


async def _handle_subscription_deleted(subscription: dict, db: AsyncSession):
    """Handle customer.subscription.deleted event"""
    try:
        # Find organization by stripe_subscription_id
        from app.db.models.subscriptions import Subscription

        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == subscription["id"]
        )
        result = await db.execute(stmt)
        subscription_record = result.scalar_one_or_none()

        if subscription_record:
            # Deactivate organization
            stmt = select(Organization).where(
                Organization.id == subscription_record.organization_id
            )
            result = await db.execute(stmt)
            organization = result.scalar_one_or_none()

            if organization:
                organization.is_active = False
                await db.commit()
                logger.info(
                    f"Organization {organization.id} deactivated due to subscription deletion"
                )
        else:
            logger.warning(f"Subscription not found: {subscription['id']}")
    except Exception as e:
        logger.error(f"Failed to handle subscription deletion: {e}")
        raise
