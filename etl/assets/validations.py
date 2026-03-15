"""Dataset release validations."""

from dagster import AssetExecutionContext, Output, asset

from etl.core.dataset_registry import DATASET_SPECS
from etl.core.releases import ReleaseManifest
from etl.core.validation import validate_dataset_release
from etl.resources.clickhouse import ClickHouseResource


def _validate_release(
    context: AssetExecutionContext, clickhouse: ClickHouseResource, manifest_dict: dict
) -> Output[dict]:
    manifest = ReleaseManifest.model_validate(manifest_dict)
    dataset_spec = DATASET_SPECS[manifest.dataset]
    results = validate_dataset_release(
        context=context,
        clickhouse=clickhouse,
        dataset_spec=dataset_spec,
        manifest=manifest,
    )
    from etl.orchestration.source_registry import validation_hook_for_dataset

    validation_hook = validation_hook_for_dataset(manifest.dataset)
    if validation_hook:
        results.update(validation_hook(context, clickhouse, manifest))
    return Output(
        value=results, metadata={"release_id": manifest.release_id, "tables": len(results)}
    )


@asset(
    name="validate_dld",
    group_name="validations",
    deps=[table.table_name for table in DATASET_SPECS["dld"].tables],
)
def validate_dld(
    context: AssetExecutionContext,
    raw_dld_files: dict,
    clickhouse: ClickHouseResource,
) -> Output[dict]:
    return _validate_release(context, clickhouse, raw_dld_files)


@asset(
    name="validate_gis",
    group_name="validations",
    deps=["gis_release_manifest", *[table.table_name for table in DATASET_SPECS["gis"].tables]],
)
def validate_gis(
    context: AssetExecutionContext,
    gis_release_manifest: dict,
    clickhouse: ClickHouseResource,
) -> Output[dict]:
    return _validate_release(context, clickhouse, gis_release_manifest)


@asset(
    name="validate_geo",
    group_name="validations",
    deps=[table.table_name for table in DATASET_SPECS["geo"].tables],
)
def validate_geo(
    context: AssetExecutionContext,
    raw_building_coordinates: dict,
    clickhouse: ClickHouseResource,
) -> Output[dict]:
    return _validate_release(context, clickhouse, raw_building_coordinates)


@asset(
    name="validate_dxbi",
    group_name="validations",
    deps=[table.table_name for table in DATASET_SPECS["dxbi"].tables],
)
def validate_dxbi(
    context: AssetExecutionContext,
    raw_dxbi_files: dict,
    clickhouse: ClickHouseResource,
) -> Output[dict]:
    return _validate_release(context, clickhouse, raw_dxbi_files)
