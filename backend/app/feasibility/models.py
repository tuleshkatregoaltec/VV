from typing import Literal, Optional

from pydantic import BaseModel, Field


class GISLandUse(BaseModel):
    type: str
    use: str


class GISPlotSummary(BaseModel):
    plot_number: str
    community_name: str
    project_name: str
    plot_area_sqm: float
    max_gfa_sqm: float
    max_height: str
    max_coverage: str
    gfa_type: str
    is_verified: bool
    land_use_summary: list[str] = Field(default_factory=list)


class LandPlot(GISPlotSummary):
    """Backward-compatible alias for older feasibility imports."""


class GISPlotDossier(BaseModel):
    plot_number: str
    community_name: str
    project_name: str
    master_developer: str | None = None
    plot_area_sqm: float
    max_gfa_sqm: float
    max_gfa_sqft: float
    max_height: str
    max_coverage: str
    gfa_type: str
    far: float | None = None
    inferred_usage: Literal["residential", "commercial", "mixed_use", "unknown"]
    site_plan_issue_date: str | None = None
    site_plan_expiry_date: str | None = None
    is_verified: bool
    verify_comments: str | None = None
    land_use: list[GISLandUse] = Field(default_factory=list)
    general_notes: list[str] = Field(default_factory=list)
    setbacks: dict[str, str] = Field(default_factory=dict)
    coordinates: list[list[float]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MarketPricingRow(BaseModel):
    unit_type: str
    transaction_count: int
    median_price_sqm: float
    avg_area_sqm: float | None = None


class LandSaleEvidence(BaseModel):
    transaction_id: str
    instance_date: str
    area_name: str
    project_name: str
    procedure_name: str
    property_usage: str
    plot_area_sqm: float
    price_aed: float
    price_sqm: float
    nearest_landmark: str | None = None


class ComparableProject(BaseModel):
    project_id: int
    project_name: str
    area_name: str
    project_status: str | None = None
    comparison_type: Literal["pricing", "pipeline"]
    score: float
    total_land_area_sqm: float | None = None
    land_area_delta_pct: float | None = None
    no_of_buildings: int | None = None
    no_of_units: int | None = None
    median_price_sqm: float | None = None
    dominant_unit_type: str | None = None
    rationale: list[str] = Field(default_factory=list)


class UnitTypeData(BaseModel):
    type: str
    count: int
    percentage: float
    avg_size_sqm: float
    avg_price_sqm: Optional[float]


class ComparableData(BaseModel):
    project_id: int
    project_name: str
    area_name: str
    no_of_buildings: int
    avg_floors: Optional[float]
    unit_mix: list[UnitTypeData]
    price_per_sqm_by_type: dict[str, float]


class HBUUnitRecommendation(BaseModel):
    unit_type: str
    share_pct: float
    avg_size_sqm: float
    price_sqm: float
    suggested_units: int


class HBUProductOption(BaseModel):
    name: str
    positioning: str
    fit_score: float
    rationale: list[str] = Field(default_factory=list)


class HBUStudy(BaseModel):
    plot_number: str
    usage: Literal["residential", "commercial", "mixed_use", "unknown"]
    market_area: str
    headline: str
    summary: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    pricing_evidence: list[ComparableProject] = Field(default_factory=list)
    competition_evidence: list[ComparableProject] = Field(default_factory=list)
    land_sales_evidence: list[LandSaleEvidence] = Field(default_factory=list)
    market_pricing: list[MarketPricingRow] = Field(default_factory=list)
    product_options: list[HBUProductOption] = Field(default_factory=list)
    recommended_mix: list[HBUUnitRecommendation] = Field(default_factory=list)
    price_per_sqm_by_type: dict[str, float] = Field(default_factory=dict)
    assumptions_patch: dict[str, float | bool | str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class FeasibilityChatRequest(BaseModel):
    messages: list[dict]
    context: dict
    history_json: str | None = None
