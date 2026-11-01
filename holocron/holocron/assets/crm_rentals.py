"""Manual downstream Dagster asset; source pipelines and schedules remain unchanged."""

from crm_rental_sql import BASE_TABLE
from dagster import MaterializeResult, asset

from holocron.assets.crm_rental_base import publish_rental_base
from holocron.platform.resources import ClickHouseResource


@asset(
    name=BASE_TABLE,
    group_name="crm",
    deps=[
        "dxbi_evidence_bronze",
        "geo_source_signatures",
        "geo_entity_links",
        "geo_location_nodes",
        "geo_location_closure",
    ],
    description="Validated rental identity ranking; manual downstream publication only.",
)
def crm_rental_ranked_base_asset(clickhouse: ClickHouseResource) -> MaterializeResult:
    marker = publish_rental_base(clickhouse.client())
    return MaterializeResult(metadata=marker)
