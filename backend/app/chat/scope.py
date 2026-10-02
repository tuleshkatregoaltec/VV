"""Freeze interpreted user cohorts for one turn; never derive scope from retrieved data."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.analytics.models import MarketBedrooms, MarketPeriodRequest
from app.market.periods import resolve_period
from app.market.reference import community_location


class ScopeError(ValueError):
    def __init__(self, code: str, field: str, message: str):
        self.code = code
        self.details = [{"field": field, "message": message}]
        super().__init__(message)


def validate_period(period: MarketPeriodRequest, reference_date: date, prefix="period"):
    required = {
        "previous_months": ("months",),
        "rolling_days": ("days",),
        "month": ("month",),
        "quarter": ("quarter",),
        "range": ("start", "end"),
    }.get(period.type, ())
    for field in required:
        if getattr(period, field) is None:
            raise ScopeError(
                "invalid_arguments",
                f"{prefix}.{field}",
                f"{period.type} requires {field}. Supply the user's requested value; ask for clarification if it is unknown.",
            )
    try:
        return resolve_period(
            period.type,
            reference_date=reference_date,
            **period.model_dump(exclude={"type"}),
        )
    except (ValueError, OverflowError):
        raise ScopeError(
            "invalid_arguments",
            prefix,
            "Supply valid calendar dates and start <= end; do not substitute another period.",
        ) from None


class MarketCohort(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    evidence_kind: Literal["listings", "sales", "rentals", "delivery", "report"]
    location: str | None = Field(default=None, min_length=1, max_length=120)
    building: str | None = Field(default=None, min_length=1, max_length=160)
    project: str | None = Field(default=None, min_length=1, max_length=160)
    projects: list[str] | None = Field(
        default=None,
        min_length=2,
        max_length=3,
        description="Exact supplied project names for an off-plan comparison report.",
    )
    bedrooms: list[MarketBedrooms] | None = Field(default=None, min_length=1, max_length=8)
    property_type: (
        Literal["apartment", "hotel_apartment", "villa", "townhouse", "office", "shop", "land"]
        | None
    ) = None
    mode: Literal["sale", "rent"] | None = None
    price_min: float | None = Field(default=None, ge=0, le=1_000_000_000)
    price_max: float | None = Field(default=None, gt=0, le=1_000_000_000)
    price_min_inclusive: bool | None = Field(
        default=None, description="Required with price_min: false for above, true for at least."
    )
    price_max_inclusive: bool | None = Field(
        default=None, description="Required with price_max: false for below, true for at most."
    )
    period: MarketPeriodRequest | None = Field(
        default=None,
        description="Explicit requested transaction/comparable-rent period. A listing inventory snapshot has no historical period. Omit when the user did not specify one.",
    )

    @model_validator(mode="after")
    def complete_bounds(self):
        for field in ("price_min", "price_max"):
            if (getattr(self, field) is None) != (getattr(self, f"{field}_inclusive") is None):
                raise ValueError(f"{field} and {field}_inclusive must be supplied together")
        if self.price_min is not None and self.price_max is not None:
            if self.price_min > self.price_max or (
                self.price_min == self.price_max
                and not (self.price_min_inclusive and self.price_max_inclusive)
            ):
                raise ValueError("Price bounds must describe a nonempty interval")
        return self


class BindMarketScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cohorts: list[MarketCohort] = Field(
        min_length=1,
        max_length=8,
        description="All explicitly requested cohorts, bound once before retrieval. Keep paired locations, bedroom counts and budgets together. Separate listing bedroom comparisons into individual cohorts. Do not invent missing constraints.",
    )

    @model_validator(mode="after")
    def unique_ids(self):
        if len({cohort.id for cohort in self.cohorts}) != len(self.cohorts):
            raise ValueError("Cohort ids must be unique")
        return self


def _kind(name: str, raw: dict) -> str | None:
    if name == "query_market_metrics":
        return raw.get("dataset")
    if name in {"get_listing_inventory", "compare_listing_age", "compare_listing_rents"}:
        return "listings"
    return "delivery" if name == "get_project_delivery_summary" else "report"


def _equivalent(field, actual, expected):
    if field in {"location", "building", "project"} and isinstance(actual, str):

        def normalized(value):
            text = " ".join(value.casefold().split())
            return community_location(text).name.casefold() if field == "location" else text

        return normalized(actual) == normalized(expected)
    if field == "bedrooms" and isinstance(actual, list):
        return all(isinstance(value, str) for value in actual) and set(actual) == set(expected)
    return actual == expected


class TurnScope:
    def __init__(self, reference_date: date):
        self.reference_date = reference_date
        self.cohorts: tuple[MarketCohort, ...] = ()

    def bind(self, request: BindMarketScopeRequest):
        if self.cohorts:
            if request.cohorts == list(self.cohorts):
                return  # An identical retry cannot change scope.
            raise ScopeError(
                "scope_conflict",
                "cohorts",
                "Scope is already frozen for this turn. A changed scope requires a new user turn.",
            )
        for index, cohort in enumerate(request.cohorts):
            if cohort.period:
                validate_period(cohort.period, self.reference_date, f"cohorts.{index}.period")
        self.cohorts = tuple(request.cohorts)

    def apply(self, name: str, raw: dict, model: type[BaseModel], scope_id: str | None):
        if not self.cohorts:
            raise ScopeError(
                "scope_required",
                "cohorts",
                "Call bind_market_scope with all explicit user constraints before retrieving data.",
            )
        kind = _kind(name, raw)
        candidates = [
            cohort
            for cohort in self.cohorts
            if cohort.evidence_kind == kind
            or (
                name == "query_market_metrics"
                and kind is None
                and cohort.evidence_kind in {"sales", "rentals"}
            )
        ]
        if scope_id is not None:
            candidates = [cohort for cohort in candidates if cohort.id == scope_id]
        if len(candidates) != 1:
            raise ScopeError(
                "scope_required",
                "scope_id",
                "Choose the id of one frozen cohort with this evidence_kind; scope cannot be added or changed during retrieval.",
            )
        cohort = candidates[0]
        kind = cohort.evidence_kind
        result = raw.copy()
        fields = cohort.model_dump(mode="json", exclude_none=True, exclude={"id", "evidence_kind"})
        if kind in {"sales", "rentals"}:
            fields["dataset"] = kind
            if "mode" in fields:
                expected_mode = "sale" if kind == "sales" else "rent"
                if fields.pop("mode") != expected_mode:
                    raise ScopeError(
                        "scope_conflict",
                        "mode",
                        "The cohort purpose conflicts with the selected dataset.",
                    )
            for bound, target in (
                ("price_min", "min_value_aed"),
                ("price_max", "max_value_aed"),
                ("price_min_inclusive", "min_value_inclusive"),
                ("price_max_inclusive", "max_value_inclusive"),
            ):
                if bound in fields:
                    fields[target] = fields.pop(bound)
        else:
            if "bedrooms" in fields:
                if len(fields["bedrooms"]) != 1:
                    raise ScopeError(
                        "unsupported_scope",
                        "bedrooms",
                        "This capability accepts one bedroom cohort per call. Declare separate cohorts before retrieval.",
                    )
                fields["bedrooms"] = fields["bedrooms"][0]
            if "property_type" in fields and kind == "listings":
                fields["property_type"] = fields["property_type"].title()
        deferred = []
        for field, expected in fields.items():
            if kind == "report":
                supported = (
                    {"projects", "period"}
                    if raw.get("kind") == "off_plan_comparison"
                    else {"location", "building", "bedrooms", "period", "property_type"}
                )
                if field not in supported or (field == "property_type" and expected != "apartment"):
                    raise ScopeError(
                        "unsupported_scope",
                        field,
                        "This report kind does not apply the frozen constraint. Disclose the limitation; do not retrieve a broader report.",
                    )
            if field not in model.model_fields:
                if field == "period" and name in {"get_listing_inventory", "compare_listing_age"}:
                    deferred.append(
                        "period applies to registered-rent comparison; inventory is a current snapshot"
                    )
                    continue
                if field == "property_type" and kind == "report" and expected == "apartment":
                    continue  # Existing report service explicitly fixes apartment evidence.
                raise ScopeError(
                    "unsupported_scope",
                    field,
                    "This capability cannot express the frozen constraint. Disclose the limitation; do not remove the constraint.",
                )
            if field in raw:
                actual = raw[field]
                if field == "period" and isinstance(actual, dict):
                    # A malformed period must be repaired, never completed by guessing.
                    try:
                        actual_period = MarketPeriodRequest.model_validate(actual, extra="forbid")
                    except ValidationError as error:
                        issue = error.errors(include_url=False, include_input=False)[0]
                        path = ".".join(["period", *(str(part) for part in issue["loc"])])
                        raise ScopeError("invalid_arguments", path, issue["msg"]) from None
                    actual_resolved = validate_period(actual_period, self.reference_date)
                    expected_resolved = validate_period(cohort.period, self.reference_date)
                    matches = (actual_resolved.start, actual_resolved.end) == (
                        expected_resolved.start,
                        expected_resolved.end,
                    )
                else:
                    matches = _equivalent(field, actual, expected)
                if not matches:
                    raise ScopeError(
                        "scope_conflict",
                        field,
                        f"Preserve frozen cohort {cohort.id}: expected {expected!r}. Omit this field to inherit it; changed constraints require a new user turn.",
                    )
            result[field] = expected
        return result, {
            "id": cohort.id,
            "constraints": cohort.model_dump(mode="json", exclude_none=True),
            "deferred": deferred,
        }
