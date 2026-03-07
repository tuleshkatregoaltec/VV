import json
import logging
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.dependencies import require_active_subscription, AuthContext
from app.feasibility.models import (
    ComparableData,
    FeasibilityChatRequest,
    GISPlotDossier,
    GISPlotSummary,
    HBUStudy,
    LandSaleEvidence,
)
from app.feasibility.normalization import Usage
from app.feasibility.service import (
    get_areas,
    get_comparable_data,
    get_gis_plot_dossier,
    get_land_sale_evidence,
    get_land_plots,
    list_plot_communities,
    search_gis_plots,
    search_land_plots,
)
from app.feasibility.agent import generate_agent_hbu_study, stream_feasibility_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/feasibility", tags=["feasibility"])


@router.get("/areas", response_model=list[str])
async def areas_endpoint(
    _: AuthContext = Depends(require_active_subscription),
):
    """Get all distinct transaction areas with sales activity."""
    return await get_areas()


@router.get("/communities", response_model=list[str])
async def communities_endpoint(
    _: AuthContext = Depends(require_active_subscription),
):
    """Get GIS plot communities ordered by activity."""
    return await list_plot_communities()


@router.get("/plots", response_model=list[GISPlotSummary])
async def plots_endpoint(
    q: str = Query(default=""),
    community: str = Query(default=""),
    min_plot_area_sqm: float | None = Query(default=None, ge=0.0),
    max_plot_area_sqm: float | None = Query(default=None, ge=0.0),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
    _: AuthContext = Depends(require_active_subscription),
):
    """Search GIS plots by plot number, project, community, and plot area."""
    return await search_gis_plots(
        q=q,
        community=community,
        min_plot_area_sqm=min_plot_area_sqm,
        max_plot_area_sqm=max_plot_area_sqm,
        offset=offset,
        limit=limit,
    )


@router.get("/plots/{plot_number}", response_model=GISPlotDossier)
async def plot_dossier_endpoint(
    plot_number: str,
    _: AuthContext = Depends(require_active_subscription),
):
    """Get full GIS-backed plot dossier for feasibility and HBU analysis."""
    dossier = await get_gis_plot_dossier(plot_number)
    if dossier is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="GIS plot not found")
    return dossier


@router.post("/hbu/{plot_number}", response_model=HBUStudy)
async def generate_hbu_endpoint(
    plot_number: str,
    usage_override: Usage | None = Query(default=None),
    _: AuthContext = Depends(require_active_subscription),
):
    """Generate an agent-authored initial HBU study for the selected GIS plot."""
    study = await generate_agent_hbu_study(plot_number, usage_override=usage_override)
    if study is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="GIS plot not found")
    return study


@router.get("/plots/{plot_number}/land-sales", response_model=list[LandSaleEvidence])
async def plot_land_sales_endpoint(
    plot_number: str,
    days: int = Query(default=1825, ge=30, le=3650),
    limit: int = Query(default=12, ge=1, le=50),
    _: AuthContext = Depends(require_active_subscription),
):
    """Get recent land sale evidence for the selected GIS plot area."""
    dossier = await get_gis_plot_dossier(plot_number)
    if dossier is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="GIS plot not found")
    return await get_land_sale_evidence(
        area_name=dossier.community_name,
        plot_area_sqm=dossier.plot_area_sqm,
        days=days,
        limit=limit,
    )


@router.get("/land", response_model=list[GISPlotSummary])
async def land_endpoint(
    area: str = Query(...),
    size_sqm: float = Query(...),
    tolerance: float = Query(default=0.25, ge=0.0, le=1.0),
    _: AuthContext = Depends(require_active_subscription),
):
    """Find land plots near a given size in the specified area."""
    return await get_land_plots(area, size_sqm, tolerance)


@router.get("/land/search", response_model=list[GISPlotSummary])
async def land_search_endpoint(
    area: str = Query(...),
    q: str = Query(..., min_length=1),
    _: AuthContext = Depends(require_active_subscription),
):
    """Legacy plot search alias backed by GIS plot data."""
    return await search_land_plots(area, q)


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
