"""Silver assets for Property Finder locations."""

from __future__ import annotations

import json

from dagster import AssetIn, MaterializeResult, asset

from holocron.resources.clickhouse import ClickHouseResource

BRONZE_COLUMNS = [
    "release_id",
    "scraped_at",
    "pf_location_id",
    "parent_pf_location_id",
    "city_pf_location_id",
    "path_ids",
    "path_depth",
    "level_type",
    "location_name",
    "alternate_name",
    "slug",
    "city_slug",
    "parent_path_name_en",
    "full_path_name_en",
    "breadcrumbs_json",
    "is_transaction_visible",
    "is_community_visible",
    "is_subcommunity_visible",
    "is_in_cms",
    "seen_in_buy",
    "seen_in_rent",
    "buy_listing_url",
    "rent_listing_url",
]

SILVER_COLUMNS = [
    "release_id",
    "scraped_at",
    "pf_location_id",
    "parent_pf_location_id",
    "city_pf_location_id",
    "path_ids",
    "path_depth",
    "level_type",
    "normalized_level",
    "location_name",
    "alternate_name",
    "slug",
    "city_slug",
    "parent_name",
    "parent_slug",
    "parent_path_name_en",
    "full_path_name_en",
    "ancestor_ids_json",
    "ancestor_names_json",
    "ancestor_slugs_json",
    "breadcrumbs_json",
    "is_leaf",
    "is_transaction_visible",
    "is_community_visible",
    "is_subcommunity_visible",
    "is_in_cms",
    "seen_in_buy",
    "seen_in_rent",
    "buy_listing_url",
    "rent_listing_url",
]


def _normalize_level(level_type: str, path_depth: int) -> str:
    if level_type == "CITY" or path_depth == 1:
        return "city"
    if level_type == "COMMUNITY" or path_depth == 2:
        return "community"
    if level_type == "SUBCOMMUNITY" or path_depth == 3:
        return "subcommunity"
    if level_type == "TOWER":
        return "tower"
    return level_type.lower()


@asset(
    name="pf_location_hierarchy",
    group_name="propertyfinder",
    tags={
        "provider": "propertyfinder",
        "dataset": "pf_locations",
        "asset_type": "silver",
        "table": "pf_location_hierarchy",
    },
    ins={"pf_locations_bronze": AssetIn(key="pf_locations")},
    description=(
        "Build a cleaned Property Finder location hierarchy from the bronze pf_locations "
        "table, deriving explicit parent/ancestor fields and normalized levels."
    ),
)
def pf_location_hierarchy(
    context,
    pf_locations_bronze,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del pf_locations_bronze

    columns, result_rows = clickhouse.query_rows(
        f"SELECT {', '.join(BRONZE_COLUMNS)} FROM pf_locations"
    )
    rows = [dict(zip(columns, row, strict=False)) for row in result_rows]
    by_id = {str(row["pf_location_id"]): row for row in rows}

    child_counts: dict[str, int] = {}
    for row in rows:
        parent_id = str(row["parent_pf_location_id"] or "")
        if parent_id:
            child_counts[parent_id] = child_counts.get(parent_id, 0) + 1

    silver_rows: list[tuple] = []
    for row in rows:
        path_ids = str(row["path_ids"] or "")
        path_parts = [part for part in path_ids.split(".") if part]
        ancestor_ids = path_parts[:-1]
        parent_id = str(row["parent_pf_location_id"] or "")
        parent_row = by_id.get(parent_id)

        parent_path_names = [
            part.strip() for part in str(row["parent_path_name_en"] or "").split(",")
        ]
        parent_path_names = [part for part in parent_path_names if part]
        ancestor_names = parent_path_names
        ancestor_slugs = [
            by_id[ancestor_id]["slug"]
            for ancestor_id in ancestor_ids
            if ancestor_id in by_id and by_id[ancestor_id].get("slug")
        ]

        silver_rows.append(
            (
                str(row["release_id"]),
                row["scraped_at"],
                str(row["pf_location_id"]),
                parent_id,
                str(row["city_pf_location_id"] or ""),
                path_ids,
                int(row["path_depth"] or 0),
                str(row["level_type"] or ""),
                _normalize_level(str(row["level_type"] or ""), int(row["path_depth"] or 0)),
                str(row["location_name"] or ""),
                str(row["alternate_name"] or ""),
                str(row["slug"] or ""),
                str(row["city_slug"] or ""),
                str(parent_row["location_name"])
                if parent_row
                else (ancestor_names[-1] if ancestor_names else ""),
                str(parent_row["slug"]) if parent_row else "",
                str(row["parent_path_name_en"] or ""),
                str(row["full_path_name_en"] or ""),
                json.dumps(ancestor_ids, ensure_ascii=False, separators=(",", ":")),
                json.dumps(ancestor_names, ensure_ascii=False, separators=(",", ":")),
                json.dumps(ancestor_slugs, ensure_ascii=False, separators=(",", ":")),
                str(row["breadcrumbs_json"] or "[]"),
                0 if child_counts.get(str(row["pf_location_id"])) else 1,
                int(row["is_transaction_visible"] or 0),
                int(row["is_community_visible"] or 0),
                int(row["is_subcommunity_visible"] or 0),
                int(row["is_in_cms"] or 0),
                int(row["seen_in_buy"] or 0),
                int(row["seen_in_rent"] or 0),
                str(row["buy_listing_url"] or ""),
                str(row["rent_listing_url"] or ""),
            )
        )

    silver_rows.sort(key=lambda item: (item[6], item[2]))
    row_count = clickhouse.replace_table_rows(
        table="pf_location_hierarchy",
        rows=silver_rows,
        column_names=SILVER_COLUMNS,
        staging_suffix="pf_location_hierarchy",
    )
    return MaterializeResult(
        metadata={
            "row_count": row_count,
            "bronze_row_count": len(rows),
        }
    )
