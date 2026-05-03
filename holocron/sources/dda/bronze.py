from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from holocron.platform.clickhouse import ClickHouseClient
from holocron.platform.raw_files import (
    download_manifest_file,
    manifest_files_by_name,
    read_csv_manifest_rows,
    require_manifest_file,
    string_value,
)
from holocron.platform.s3 import S3Client
from holocron.sources.dda.source import DDA_SOURCE_NAME


@dataclass(frozen=True, slots=True)
class TableLoadSpec:
    csv_name: str
    table_name: str
    column_names: tuple[str, ...]
    row_builder: Any


def _string(value: Any) -> str:
    return string_value(value)


def _int(value: Any) -> int:
    parsed = _string(value)
    if not parsed:
        return 0
    try:
        return int(parsed)
    except ValueError:
        return int(float(parsed))


def _float(value: Any) -> float:
    parsed = _string(value).replace(",", "")
    if not parsed:
        return 0.0
    return float(parsed)


def _uint8(value: Any) -> int:
    parsed = _string(value).lower()
    if parsed in {"", "0", "false", "no", "n"}:
        return 0
    if parsed in {"1", "true", "yes", "y"}:
        return 1
    return 1 if _int(parsed) > 0 else 0


def _date_or_none(value: Any) -> date | None:
    parsed = _string(value)
    if not parsed:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%d-%b-%Y",
        "%d-%B-%Y",
    ):
        try:
            return datetime.strptime(parsed, fmt).date()
        except ValueError:
            continue
    return None


def _land_plot_row(row: dict[str, str]) -> tuple:
    return (
        _string(row.get("plot_number")),
        _string(row.get("old_numbers")),
        _string(row.get("project_name")),
        _string(row.get("community_name")),
        _string(row.get("master_developer")),
        _float(row.get("plot_area_sqm")),
        _float(row.get("plot_area_sqft")),
        _float(row.get("max_gfa_sqm")),
        _float(row.get("max_gfa_sqft")),
        _string(row.get("max_height")),
        _string(row.get("max_coverage")),
        _date_or_none(row.get("site_plan_issue_date")),
        _date_or_none(row.get("site_plan_expiry_date")),
        _string(row.get("side1_building")),
        _string(row.get("side1_podium")),
        _string(row.get("side2_building")),
        _string(row.get("side2_podium")),
        _string(row.get("side3_building")),
        _string(row.get("side3_podium")),
        _string(row.get("side4_building")),
        _string(row.get("side4_podium")),
        _string(row.get("land_use")),
        _string(row.get("general_notes")),
        _string(row.get("coordinates")),
        _string(row.get("landuse_symbols")),
        _string(row.get("gfa_type")),
        _uint8(row.get("is_verified")),
        _string(row.get("verify_comments")),
    )


def _project_area_row(row: dict[str, str]) -> tuple:
    return (_int(row.get("object_id")), _string(row.get("project_name")), _string(row.get("rings")))


def _subproject_area_row(row: dict[str, str]) -> tuple:
    return (
        _int(row.get("object_id")),
        _string(row.get("project_id")),
        _string(row.get("project_name")),
        _string(row.get("entity_name")),
        _string(row.get("developer_name")),
        _string(row.get("master_project_name")),
        _string(row.get("original_plot_number")),
        _string(row.get("project_logo")),
        _string(row.get("rings")),
    )


def _building_limit_row(row: dict[str, str]) -> tuple:
    return (_int(row.get("object_id")), _string(row.get("plot_number")), _string(row.get("rings")))


def _podium_limit_row(row: dict[str, str]) -> tuple:
    return (
        _int(row.get("object_id")),
        _string(row.get("plot_number")),
        _string(row.get("max_height")),
        _string(row.get("rings")),
    )


def _plot_feature_row(row: dict[str, str]) -> tuple:
    return (
        _int(row.get("object_id")),
        _string(row.get("plot_number")),
        _int(row.get("feature_type_code")),
        _string(row.get("feature_type_label")),
        _float(row.get("feature_area_sqm")),
        _float(row.get("feature_perimeter_m")),
        _string(row.get("rings")),
    )


def _frozen_plot_row(row: dict[str, str]) -> tuple:
    return (
        _int(row.get("object_id")),
        _string(row.get("plot_number")),
        _string(row.get("old_plot_numbers")),
        _uint8(row.get("is_frozen")),
        _float(row.get("plot_area_sqm")),
        _float(row.get("plot_perimeter_m")),
        _string(row.get("gfa_type")),
        _string(row.get("gfa_sqm_t")),
        _string(row.get("gfa_sqft_t")),
        _string(row.get("rings")),
    )


def _landuse_symbol_row(row: dict[str, str]) -> tuple:
    return (
        _int(row.get("object_id")),
        _string(row.get("landuse")),
        _string(row.get("landuse_character")),
        _string(row.get("landuse_id")),
        _float(row.get("lat")),
        _float(row.get("lng")),
    )


def _built_to_line_row(row: dict[str, str]) -> tuple:
    return (_int(row.get("object_id")), _string(row.get("plot_number")), _string(row.get("paths")))


def _arcade_row(row: dict[str, str]) -> tuple:
    return (_int(row.get("object_id")), _string(row.get("plot_number")), _string(row.get("rings")))


def _retail_row(row: dict[str, str]) -> tuple:
    return (_int(row.get("object_id")), _string(row.get("plot_number")), _string(row.get("rings")))


_TABLE_SPECS = (
    TableLoadSpec(
        csv_name="dda_plots.csv",
        table_name="dda_land_plots",
        column_names=(
            "plot_number",
            "old_numbers",
            "project_name",
            "community_name",
            "master_developer",
            "plot_area_sqm",
            "plot_area_sqft",
            "max_gfa_sqm",
            "max_gfa_sqft",
            "max_height",
            "max_coverage",
            "site_plan_issue_date",
            "site_plan_expiry_date",
            "side1_building",
            "side1_podium",
            "side2_building",
            "side2_podium",
            "side3_building",
            "side3_podium",
            "side4_building",
            "side4_podium",
            "land_use",
            "general_notes",
            "coordinates",
            "landuse_symbols",
            "gfa_type",
            "is_verified",
            "verify_comments",
        ),
        row_builder=_land_plot_row,
    ),
    TableLoadSpec(
        csv_name="dda_project_areas.csv",
        table_name="dda_project_areas",
        column_names=("object_id", "project_name", "rings"),
        row_builder=_project_area_row,
    ),
    TableLoadSpec(
        csv_name="dda_subproject_areas.csv",
        table_name="dda_subproject_areas",
        column_names=(
            "object_id",
            "project_id",
            "project_name",
            "entity_name",
            "developer_name",
            "master_project_name",
            "original_plot_number",
            "project_logo",
            "rings",
        ),
        row_builder=_subproject_area_row,
    ),
    TableLoadSpec(
        csv_name="dda_plot_building_limits.csv",
        table_name="dda_plot_building_limits",
        column_names=("object_id", "plot_number", "rings"),
        row_builder=_building_limit_row,
    ),
    TableLoadSpec(
        csv_name="dda_plot_podium_limits.csv",
        table_name="dda_plot_podium_limits",
        column_names=("object_id", "plot_number", "max_height", "rings"),
        row_builder=_podium_limit_row,
    ),
    TableLoadSpec(
        csv_name="dda_plot_features.csv",
        table_name="dda_plot_features",
        column_names=(
            "object_id",
            "plot_number",
            "feature_type_code",
            "feature_type_label",
            "feature_area_sqm",
            "feature_perimeter_m",
            "rings",
        ),
        row_builder=_plot_feature_row,
    ),
    TableLoadSpec(
        csv_name="dda_frozen_plots.csv",
        table_name="dda_frozen_plots",
        column_names=(
            "object_id",
            "plot_number",
            "old_plot_numbers",
            "is_frozen",
            "plot_area_sqm",
            "plot_perimeter_m",
            "gfa_type",
            "gfa_sqm_t",
            "gfa_sqft_t",
            "rings",
        ),
        row_builder=_frozen_plot_row,
    ),
    TableLoadSpec(
        csv_name="dda_landuse_symbols.csv",
        table_name="dda_landuse_symbols",
        column_names=("object_id", "landuse", "landuse_character", "landuse_id", "lat", "lng"),
        row_builder=_landuse_symbol_row,
    ),
    TableLoadSpec(
        csv_name="dda_plot_built_to_lines.csv",
        table_name="dda_plot_built_to_lines",
        column_names=("object_id", "plot_number", "paths"),
        row_builder=_built_to_line_row,
    ),
    TableLoadSpec(
        csv_name="dda_plot_arcades.csv",
        table_name="dda_plot_arcades",
        column_names=("object_id", "plot_number", "rings"),
        row_builder=_arcade_row,
    ),
    TableLoadSpec(
        csv_name="dda_plot_retail.csv",
        table_name="dda_plot_retail",
        column_names=("object_id", "plot_number", "rings"),
        row_builder=_retail_row,
    ),
)


def _schema_sql_path() -> Path:
    return Path(__file__).resolve().parents[2] / "lib" / "sql" / "clickhouse_schema.sql"


def _iter_sql_statements(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def ensure_schema(*, clickhouse: ClickHouseClient) -> None:
    sql_path = _schema_sql_path()
    if not sql_path.exists():
        raise FileNotFoundError(f"Missing ClickHouse schema file: {sql_path}")
    for statement in _iter_sql_statements(sql_path.read_text(encoding="utf-8")):
        clickhouse.command(statement)


def load_release_to_clickhouse(
    *,
    raw_release: dict[str, Any],
    s3: S3Client,
    clickhouse: ClickHouseClient,
) -> dict[str, Any]:
    source_name = _string(raw_release.get("source"))
    if source_name != DDA_SOURCE_NAME:
        raise ValueError(f"Expected raw_release.source={DDA_SOURCE_NAME}, got {source_name!r}")

    run_id = _string(raw_release.get("run_id"))
    if not run_id:
        raise ValueError("raw_release.run_id is required")

    files_by_name = manifest_files_by_name(raw_release)
    table_row_counts: dict[str, int] = {}
    parsed_rows_by_table: dict[str, list[tuple]] = {}

    with TemporaryDirectory(prefix=f"holocron-dda-bronze-{run_id}-") as scratch:
        scratch_path = Path(scratch)
        for spec in _TABLE_SPECS:
            file_entry = require_manifest_file(files_by_name, spec.csv_name)
            local_path = download_manifest_file(
                file_name=spec.csv_name,
                file_entry=file_entry,
                s3=s3,
                scratch_path=scratch_path,
                source_label="DDA",
            )
            csv_rows = read_csv_manifest_rows(
                path=local_path,
                file_entry=file_entry,
                source_label="DDA",
            )
            parsed_rows_by_table[spec.table_name] = [spec.row_builder(row) for row in csv_rows]

    ensure_schema(clickhouse=clickhouse)
    for spec in _TABLE_SPECS:
        rows = parsed_rows_by_table[spec.table_name]
        row_count = clickhouse.replace_table_rows(
            table=spec.table_name,
            rows=rows,
            column_names=spec.column_names,
            staging_suffix=run_id,
        )
        table_row_counts[spec.table_name] = row_count

    return {
        "source": source_name,
        "run_id": run_id,
        "table_row_counts": table_row_counts,
        "table_count": len(table_row_counts),
        "total_rows": sum(table_row_counts.values()),
    }
