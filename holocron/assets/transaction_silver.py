"""Deterministic transaction-location silver assets for phase 1 entity resolution."""

from __future__ import annotations

from dagster import AssetIn, MaterializeResult, asset

from holocron.lib.entity_normalization import (
    dedupe_preserve_order,
    normalize_identifier,
    normalize_text,
    parse_float,
    parse_iso_date,
    parse_json_list,
    split_location_path,
    to_json,
    token_bag,
)
from holocron.resources.clickhouse import ClickHouseResource

SILVER_COLUMNS = [
    "release_id",
    "scraped_at",
    "source_name",
    "source_table",
    "source_record_key",
    "source_system_id",
    "transaction_kind",
    "transaction_date",
    "raw_display_name",
    "normalized_display_name",
    "normalized_tokens_json",
    "entity_hint_type",
    "relationship_hint_type",
    "area_name_raw",
    "area_name_normalized",
    "project_name_raw",
    "project_name_normalized",
    "building_name_raw",
    "building_name_normalized",
    "property_number_raw",
    "property_number_normalized",
    "unit_number_raw",
    "unit_number_normalized",
    "plot_number_raw",
    "plot_number_normalized",
    "lat",
    "lng",
    "hierarchy_json",
    "source_confidence_notes",
]

_PF_HIERARCHY_COLUMNS = [
    "pf_location_id",
    "normalized_level",
    "location_name",
    "parent_name",
    "ancestor_names_json",
]


def _sort_date_key(value) -> str:
    return value.isoformat() if value is not None else ""


def _silver_row(
    *,
    release_id: str,
    scraped_at,
    source_name: str,
    source_table: str,
    source_record_key: str,
    source_system_id: str,
    transaction_kind: str,
    transaction_date,
    raw_display_name: str,
    entity_hint_type: str,
    relationship_hint_type: str,
    area_name_raw: str = "",
    project_name_raw: str = "",
    building_name_raw: str = "",
    property_number_raw: str = "",
    unit_number_raw: str = "",
    plot_number_raw: str = "",
    lat: float | None = None,
    lng: float | None = None,
    hierarchy: list[str] | None = None,
    source_confidence_notes: str = "",
) -> tuple:
    normalized_display_name = normalize_text(raw_display_name)
    return (
        release_id,
        scraped_at,
        source_name,
        source_table,
        source_record_key,
        source_system_id,
        transaction_kind,
        transaction_date,
        raw_display_name,
        normalized_display_name,
        to_json(token_bag(raw_display_name)),
        entity_hint_type,
        relationship_hint_type,
        area_name_raw,
        normalize_text(area_name_raw),
        project_name_raw,
        normalize_text(project_name_raw),
        building_name_raw,
        normalize_text(building_name_raw),
        property_number_raw,
        normalize_identifier(property_number_raw),
        unit_number_raw,
        normalize_identifier(unit_number_raw),
        plot_number_raw,
        normalize_identifier(plot_number_raw),
        lat,
        lng,
        to_json(hierarchy or []),
        source_confidence_notes,
    )


def _bay_hierarchy_names(row: dict) -> list[str]:
    ancestors = [
        str(row["bayut_location_l3_name_en"] or ""),
        str(row["bayut_location_l4_name_en"] or ""),
        str(row["bayut_location_l5_name_en"] or ""),
        str(row["bayut_location_l6_name_en"] or ""),
    ]
    leaf = str(row["bayut_leaf_location_name_en"] or "")
    return dedupe_preserve_order([*ancestors, leaf])


def _bay_silver_rows(rows: list[dict], *, source_table: str, transaction_kind: str) -> list[tuple]:
    silver_rows: list[tuple] = []
    for row in rows:
        hierarchy_names = _bay_hierarchy_names(row)
        leaf_name = str(row["bayut_leaf_location_name_en"] or "")
        ancestor_names = hierarchy_names[:-1] if leaf_name and hierarchy_names else hierarchy_names
        area_name = ancestor_names[0] if ancestor_names else leaf_name
        project_name = ancestor_names[-1] if ancestor_names else ""
        lat = parse_float(row["bayut_latitude"]) or parse_float(row["latitude"])
        lng = parse_float(row["bayut_longitude"]) or parse_float(row["longitude"])
        silver_rows.append(
            _silver_row(
                release_id=str(row["release_id"]),
                scraped_at=row["scraped_at"],
                source_name="bayut",
                source_table=source_table,
                source_record_key=str(row["transaction_hash_id"]),
                source_system_id=str(row["bayut_leaf_location_id"] or ""),
                transaction_kind=transaction_kind,
                transaction_date=parse_iso_date(row["transaction_date"]),
                raw_display_name=leaf_name,
                entity_hint_type="building_or_project" if leaf_name else "location",
                relationship_hint_type="located_in_hierarchy",
                area_name_raw=area_name,
                project_name_raw=project_name,
                building_name_raw=leaf_name,
                unit_number_raw=str(row.get("unit_number") or ""),
                lat=lat,
                lng=lng,
                hierarchy=hierarchy_names,
                source_confidence_notes=(
                    "Bayut hierarchy heuristic: area=first ancestor, project=deepest ancestor, "
                    "building=leaf location."
                ),
            )
        )
    return silver_rows


def _dxbi_silver_rows(rows: list[dict], *, source_table: str, transaction_kind: str) -> list[tuple]:
    silver_rows: list[tuple] = []
    for row in rows:
        parts = split_location_path(row["location_path"])
        building_name = parts[0] if parts else str(row["location_path"] or "")
        area_name = parts[-1] if len(parts) >= 2 else ""
        project_name = parts[1] if len(parts) >= 3 else ""
        transaction_date_value = (
            parse_iso_date(row["transaction_date"])
            if "transaction_date" in row
            else parse_iso_date(row["lease_start_date"])
        )
        silver_rows.append(
            _silver_row(
                release_id=str(row["run_id"]),
                scraped_at=row["scraped_at"],
                source_name="dxbinteract",
                source_table=source_table,
                source_record_key=str(row["transaction_key"]),
                source_system_id=str(row["scope_slug"] or ""),
                transaction_kind=transaction_kind,
                transaction_date=transaction_date_value,
                raw_display_name=str(row["location_path"] or ""),
                entity_hint_type="building_or_project" if len(parts) >= 2 else "location",
                relationship_hint_type="located_in_hierarchy",
                area_name_raw=area_name,
                project_name_raw=project_name,
                building_name_raw=building_name,
                lat=None,
                lng=None,
                hierarchy=parts,
                source_confidence_notes=(
                    "DXBI location heuristic: path is treated as leaf-first, with the final "
                    "component used as the broader area."
                ),
            )
        )
    return silver_rows


def _pf_area_name(level: str, hierarchy_names: list[str], location_name: str) -> str:
    for name in hierarchy_names:
        if normalize_text(name) != "dubai":
            return name
    if level in {"community", "subcommunity"}:
        return location_name
    return ""


def _pf_building_and_project(
    level: str, location_name: str, parent_name: str
) -> tuple[str, str, str]:
    if level == "tower":
        return "building", location_name, parent_name
    if level in {"community", "subcommunity", "city"}:
        return "area", "", ""
    return "location", "", parent_name


def _pf_silver_rows(
    rows: list[dict], hierarchy_by_id: dict[str, dict], *, source_table: str, transaction_kind: str
) -> list[tuple]:
    silver_rows: list[tuple] = []
    for row in rows:
        location_id = str(
            row["propertyfinder_location_id"] or row["captured_from_pf_location_id"] or ""
        )
        hierarchy_row = hierarchy_by_id.get(location_id, {})
        level = str(hierarchy_row.get("normalized_level") or "").strip()
        location_name = str(row["location_name"] or hierarchy_row.get("location_name") or "")
        parent_name = str(hierarchy_row.get("parent_name") or "")
        ancestor_names = [
            s
            for item in parse_json_list(hierarchy_row.get("ancestor_names_json") or "[]")
            if (s := str(item).strip())
        ]
        hierarchy_names = dedupe_preserve_order([*ancestor_names, location_name])
        entity_hint_type, building_name, project_name = _pf_building_and_project(
            level,
            location_name,
            parent_name,
        )
        area_name = _pf_area_name(level, ancestor_names, location_name)
        confidence_note = (
            "PF hierarchy-backed mapping from pf_location_hierarchy."
            if hierarchy_row
            else "PF fallback mapping without hierarchy row; location fields come from transaction row."
        )
        silver_rows.append(
            _silver_row(
                release_id=str(row["release_id"]),
                scraped_at=row["scraped_at"],
                source_name="propertyfinder",
                source_table=source_table,
                source_record_key=str(row["pf_transaction_id"]),
                source_system_id=location_id,
                transaction_kind=transaction_kind,
                transaction_date=row["transaction_date"],
                raw_display_name=location_name,
                entity_hint_type=entity_hint_type,
                relationship_hint_type="located_in_hierarchy",
                area_name_raw=area_name or str(row["high_level_location_name"] or ""),
                project_name_raw=project_name,
                building_name_raw=building_name,
                property_number_raw=str(row["property_number"] or ""),
                lat=None,
                lng=None,
                hierarchy=hierarchy_names,
                source_confidence_notes=confidence_note,
            )
        )
    return silver_rows


@asset(
    name="bay_transaction_location_silver",
    group_name="bayut",
    tags={
        "provider": "bayut",
        "dataset": "bay_transactions",
        "asset_type": "silver",
        "table": "bay_transaction_location_silver",
    },
    ins={
        "bay_sale_transactions_bronze": AssetIn(key="bay_sale_transactions"),
        "bay_rental_transactions_bronze": AssetIn(key="bay_rental_transactions"),
    },
    description=(
        "Build deterministic Bayut transaction location silver rows with normalized names, "
        "hierarchy output, and stable source keys."
    ),
)
def bay_transaction_location_silver(
    context,
    bay_sale_transactions_bronze,
    bay_rental_transactions_bronze,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del context, bay_sale_transactions_bronze, bay_rental_transactions_bronze

    sale_columns, sale_result_rows = clickhouse.query_rows(
        """
        SELECT
            release_id, scraped_at, transaction_hash_id, transaction_date, latitude, longitude,
            bayut_latitude, bayut_longitude, bayut_leaf_location_id, bayut_leaf_location_name_en,
            bayut_location_l3_name_en, bayut_location_l4_name_en, bayut_location_l5_name_en,
            bayut_location_l6_name_en, unit_number
        FROM bay_sale_transactions
        """
    )
    rental_columns, rental_result_rows = clickhouse.query_rows(
        """
        SELECT
            release_id, scraped_at, transaction_hash_id, transaction_date, latitude, longitude,
            bayut_latitude, bayut_longitude, bayut_leaf_location_id, bayut_leaf_location_name_en,
            bayut_location_l3_name_en, bayut_location_l4_name_en, bayut_location_l5_name_en,
            bayut_location_l6_name_en, '' AS unit_number
        FROM bay_rental_transactions
        """
    )

    sale_rows = [dict(zip(sale_columns, row, strict=False)) for row in sale_result_rows]
    rental_rows = [dict(zip(rental_columns, row, strict=False)) for row in rental_result_rows]
    silver_rows = [
        *_bay_silver_rows(sale_rows, source_table="bay_sale_transactions", transaction_kind="sale"),
        *_bay_silver_rows(
            rental_rows,
            source_table="bay_rental_transactions",
            transaction_kind="rent",
        ),
    ]
    silver_rows.sort(key=lambda item: (_sort_date_key(item[7]), item[4]))
    row_count = clickhouse.replace_table_rows(
        table="bay_transaction_location_silver",
        rows=silver_rows,
        column_names=SILVER_COLUMNS,
        staging_suffix="bay_transaction_location_silver",
    )
    return MaterializeResult(
        metadata={
            "row_count": row_count,
            "sale_bronze_row_count": len(sale_rows),
            "rental_bronze_row_count": len(rental_rows),
        }
    )


@asset(
    name="dxbi_transaction_location_silver",
    group_name="dxbinteract",
    tags={
        "provider": "dxbinteract",
        "dataset": "dxbi_transactions",
        "asset_type": "silver",
        "table": "dxbi_transaction_location_silver",
    },
    ins={
        "dxbi_sale_transactions_bronze": AssetIn(key="dxbi_sale_transactions"),
        "dxbi_rental_transactions_bronze": AssetIn(key="dxbi_rental_transactions"),
    },
    description=(
        "Build deterministic DXBI transaction location silver rows by parsing location_path and "
        "standardizing hierarchy hints."
    ),
)
def dxbi_transaction_location_silver(
    context,
    dxbi_sale_transactions_bronze,
    dxbi_rental_transactions_bronze,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del context, dxbi_sale_transactions_bronze, dxbi_rental_transactions_bronze

    sale_columns, sale_result_rows = clickhouse.query_rows(
        """
        SELECT
            run_id, scraped_at, transaction_key, scope_slug, location_path, transaction_date
        FROM dxbi_sale_transactions
        """
    )
    rental_columns, rental_result_rows = clickhouse.query_rows(
        """
        SELECT
            run_id, scraped_at, transaction_key, scope_slug, location_path, lease_start_date
        FROM dxbi_rental_transactions
        """
    )

    sale_rows = [dict(zip(sale_columns, row, strict=False)) for row in sale_result_rows]
    rental_rows = [dict(zip(rental_columns, row, strict=False)) for row in rental_result_rows]
    silver_rows = [
        *_dxbi_silver_rows(
            sale_rows,
            source_table="dxbi_sale_transactions",
            transaction_kind="sale",
        ),
        *_dxbi_silver_rows(
            rental_rows,
            source_table="dxbi_rental_transactions",
            transaction_kind="rent",
        ),
    ]
    silver_rows.sort(key=lambda item: (_sort_date_key(item[7]), item[4]))
    row_count = clickhouse.replace_table_rows(
        table="dxbi_transaction_location_silver",
        rows=silver_rows,
        column_names=SILVER_COLUMNS,
        staging_suffix="dxbi_transaction_location_silver",
    )
    return MaterializeResult(
        metadata={
            "row_count": row_count,
            "sale_bronze_row_count": len(sale_rows),
            "rental_bronze_row_count": len(rental_rows),
        }
    )


@asset(
    name="pf_transaction_location_silver",
    group_name="propertyfinder",
    tags={
        "provider": "propertyfinder",
        "dataset": "pf_transactions",
        "asset_type": "silver",
        "table": "pf_transaction_location_silver",
    },
    ins={
        "pf_sale_transactions_bronze": AssetIn(key="pf_sale_transactions"),
        "pf_rental_transactions_bronze": AssetIn(key="pf_rental_transactions"),
        "pf_location_hierarchy_silver": AssetIn(key="pf_location_hierarchy"),
    },
    description=(
        "Build deterministic Property Finder transaction location silver rows by joining "
        "transactions to the cleaned PF location hierarchy."
    ),
)
def pf_transaction_location_silver(
    context,
    pf_sale_transactions_bronze,
    pf_rental_transactions_bronze,
    pf_location_hierarchy_silver,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del (
        context,
        pf_sale_transactions_bronze,
        pf_rental_transactions_bronze,
        pf_location_hierarchy_silver,
    )

    hierarchy_columns, hierarchy_result_rows = clickhouse.query_rows(
        f"SELECT {', '.join(_PF_HIERARCHY_COLUMNS)} FROM pf_location_hierarchy"
    )
    hierarchy_rows = [
        dict(zip(hierarchy_columns, row, strict=False)) for row in hierarchy_result_rows
    ]
    hierarchy_by_id = {str(row["pf_location_id"]): row for row in hierarchy_rows}

    sale_columns, sale_result_rows = clickhouse.query_rows(
        """
        SELECT
            release_id, scraped_at, pf_transaction_id, transaction_date, property_number,
            high_level_location_name, location_name, propertyfinder_location_id,
            captured_from_pf_location_id
        FROM pf_sale_transactions
        """
    )
    rental_columns, rental_result_rows = clickhouse.query_rows(
        """
        SELECT
            release_id, scraped_at, pf_transaction_id, transaction_date, property_number,
            high_level_location_name, location_name, propertyfinder_location_id,
            captured_from_pf_location_id
        FROM pf_rental_transactions
        """
    )

    sale_rows = [dict(zip(sale_columns, row, strict=False)) for row in sale_result_rows]
    rental_rows = [dict(zip(rental_columns, row, strict=False)) for row in rental_result_rows]
    silver_rows = [
        *_pf_silver_rows(
            sale_rows,
            hierarchy_by_id,
            source_table="pf_sale_transactions",
            transaction_kind="sale",
        ),
        *_pf_silver_rows(
            rental_rows,
            hierarchy_by_id,
            source_table="pf_rental_transactions",
            transaction_kind="rent",
        ),
    ]
    silver_rows.sort(key=lambda item: (_sort_date_key(item[7]), item[4]))
    row_count = clickhouse.replace_table_rows(
        table="pf_transaction_location_silver",
        rows=silver_rows,
        column_names=SILVER_COLUMNS,
        staging_suffix="pf_transaction_location_silver",
    )
    return MaterializeResult(
        metadata={
            "row_count": row_count,
            "sale_bronze_row_count": len(sale_rows),
            "rental_bronze_row_count": len(rental_rows),
            "hierarchy_row_count": len(hierarchy_rows),
        }
    )
