from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.area.models import AreaDetailResponse, AreaListResponse
from app.area.service import get_area_detail, list_areas
from app.core.decorators import cached_endpoint
from app.core.dependencies import AuthContext, require_active_subscription

router = APIRouter(prefix="/api/v1/areas", tags=["areas"])


@router.get("", response_model=AreaListResponse)
@cached_endpoint(prefix="areas_list_v3", expire=3600)
async def areas_list(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    sort_by: Literal[
        "units", "volume", "transactions", "yield", "completion", "developers"
    ] = Query(default="units"),
    search: str | None = Query(default=None, max_length=120),
    context: AuthContext = Depends(require_active_subscription),
):
    return await list_areas(limit=limit, offset=offset, sort_by=sort_by, search=search)


@router.get("/{area_name}", response_model=AreaDetailResponse)
@cached_endpoint(prefix="area_detail_v2", expire=3600)
async def area_detail(
    area_name: str,
    context: AuthContext = Depends(require_active_subscription),
):
    try:
        return await get_area_detail(area_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
