"""Row-count validations for ClickHouse tables."""

from __future__ import annotations

from dagster import AssetExecutionContext, Config, Output, asset

from etl.lib.dataset_specs import DLD_FILES, GIS_FILES, GEO_FILES
from etl.resources.clickhouse import ClickHouseResource

_DLD_TABLES = [f.ch_table for f in DLD_FILES]
_GIS_TABLES = [f.ch_table for f in GIS_FILES]
_GEO_TABLES = [f.ch_table for f in GEO_FILES]


class ValidationConfig(Config):
    min_rows: int = 1


def _check_table(
    context: AssetExecutionContext, clickhouse: ClickHouseResource, table: str, min_rows: int
) -> int:
    count = int(clickhouse.query_scalar(f"SELECT count() FROM {table}"))
    context.log.info(f"{table}: {count:,} rows")
    if count < min_rows:
        raise ValueError(f"Validation failed: {table} has {count} rows (min {min_rows})")
    return count


def _make_validation_asset(name: str, tables: list[str], deps: list[str]):
    @asset(name=name, group_name="validations", deps=deps)
    def _asset(
        context: AssetExecutionContext,
        config: ValidationConfig,
        clickhouse: ClickHouseResource,
    ) -> Output[dict]:
        results = {t: _check_table(context, clickhouse, t, config.min_rows) for t in tables}
        context.log.info(f"All {name} checks passed")
        return Output(value=results, metadata=results)

    return _asset


validate_dld = _make_validation_asset("validate_dld", _DLD_TABLES, deps=_DLD_TABLES)
validate_gis = _make_validation_asset("validate_gis", _GIS_TABLES, deps=_GIS_TABLES)
validate_geo = _make_validation_asset("validate_geo", _GEO_TABLES, deps=_GEO_TABLES)
