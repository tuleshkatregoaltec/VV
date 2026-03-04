import json
import logging
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.dependencies import require_active_subscription, AuthContext
from app.feasibility.models import LandPlot, ComparableData, FeasibilityChatRequest
from app.feasibility.service import get_areas, get_land_plots, get_comparable_data
from app.feasibility.agent import stream_feasibility_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/feasibility", tags=["feasibility"])


@router.get("/areas", response_model=list[str])
async def areas_endpoint(
    _: AuthContext = Depends(require_active_subscription),
):
    """Get all distinct area names from land registry."""
    return await get_areas()


@router.get("/land", response_model=list[LandPlot])
async def land_endpoint(
    area: str = Query(...),
    size_sqm: float = Query(...),
    tolerance: float = Query(default=0.25, ge=0.0, le=1.0),
    _: AuthContext = Depends(require_active_subscription),
):
    """Find land plots near a given size in the specified area."""
    return await get_land_plots(area, size_sqm, tolerance)


@router.get("/comparable", response_model=ComparableData)
async def comparable_endpoint(
    project_ids: str = Query(..., description="Comma-separated project IDs"),
    _: AuthContext = Depends(require_active_subscription),
):
    """Get aggregated comparable data for a set of projects."""
    ids = [int(x.strip()) for x in project_ids.split(",") if x.strip().isdigit()]
    result = await get_comparable_data(ids)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=404, detail="No data found for given project IDs"
        )
    return result


@router.post("/chat/stream")
async def chat_stream_endpoint(
    request: FeasibilityChatRequest,
    _: AuthContext = Depends(require_active_subscription),
):
    """Stream LLM feasibility assistant response via SSE."""

    async def event_stream():
        try:
            async for chunk in stream_feasibility_response(
                request.messages, request.context, request.history_json
            ):
                yield chunk
        except Exception as e:
            logger.exception("Error in feasibility chat stream endpoint")
            yield f"data: {json.dumps({'type': 'error', 'error': 'Internal server error'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
