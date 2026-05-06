from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import AuthContext, require_active_subscription
from app.listings.models import ListingDetailResponse, ListingListResponse, ListingMode
from app.listings.service import get_demo_listing, list_demo_listings
from app.postgres import get_db_session

router = APIRouter(prefix="/api/v1/listings", tags=["listings"])


@router.get("", response_model=ListingListResponse)
async def list_listings(
    mode: ListingMode = Query(default="rent"),
    limit: int = Query(default=48, ge=1, le=120),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=160),
    area: str | None = Query(default=None, max_length=160),
    property_type: str | None = Query(default=None, max_length=120),
    bedrooms: str | None = Query(default=None, max_length=40),
    price_min: int | None = Query(default=None, ge=0),
    price_max: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db_session),
    context: AuthContext = Depends(require_active_subscription),
):
    """List locally imported PropertyFinder listings for the demo."""
    return await list_demo_listings(
        db=db,
        mode=mode,
        limit=limit,
        offset=offset,
        search=search,
        area=area,
        property_type=property_type,
        bedrooms=bedrooms,
        price_min=price_min,
        price_max=price_max,
    )


@router.get("/{listing_id}", response_model=ListingDetailResponse)
async def get_listing(
    listing_id: str,
    db: AsyncSession = Depends(get_db_session),
    context: AuthContext = Depends(require_active_subscription),
):
    """Get one locally imported PropertyFinder listing for the demo."""
    return await get_demo_listing(db, listing_id)
