from typing import Literal

ProjectFilterType = Literal["project", "master", "virtual_master"]
ProjectScopeType = Literal["project", "master", "virtual_master", "market"]

# Server-side market type filters — frontend passes market_type, never raw predicates.
# See analytics_architecture.md for taxonomy rationale.
MARKET_FILTERS: dict[str, dict] = {
    "residential_units": {
        "property_type_en": "Unit",
        "property_usage_en": "Residential",
        "trans_group_en": "Sales",
    },
    "villas": {
        "property_type_en": "Villa",
        "trans_group_en": "Sales",
    },
    "commercial_units": {
        "property_type_en": "Unit",
        "property_usage_en__in": ["Commercial", "Hospitality"],
        "trans_group_en": "Sales",
    },
    "bulk_building": {
        "property_type_en": "Building",
        "trans_group_en": "Sales",
    },
    "land": {
        "property_type_en": "Land",
        "trans_group_en": "Sales",
    },
    "mortgages": {"trans_group_en": "Mortgages"},
    "gifts": {"trans_group_en": "Gifts"},
}


def project_filter_clause(filter_type: ProjectScopeType) -> str:
    """WHERE clause condition for a given filter type.

    master: matches rows with master_project_en = X OR orphaned rows whose
    project_name_en starts with X + ' - ' (absorbs inconsistently-linked sub-projects).
    """
    if filter_type == "market":
        return "1 = 1"
    if filter_type == "master":
        return """(master_project_en = {project_name:String}
            OR (lower(project_name_en) LIKE concat(lower({project_name:String}), ' - %')
                AND (master_project_en = '' OR master_project_en IS NULL)))"""
    if filter_type == "virtual_master":
        return "project_name_en LIKE {project_name:String}"
    return "project_name_en = {project_name:String}"


# Community predicate over DLD-shaped rows (area_name_en, master_project_en). A known master
# project wins; an official DLD area that also holds other communities matches only rows
# without a master project. Terms come from market.reference.community_location.
LOCATION_PREDICATE = (
    "(lowerUTF8(master_project_en) IN {loc_masters:Array(String)}"
    " OR lowerUTF8(area_name_en) IN {loc_areas:Array(String)}"
    " OR (master_project_en = '' AND lowerUTF8(area_name_en) IN {loc_official:Array(String)}))"
)


def location_parameters(location) -> dict[str, list[str]]:
    return {
        "loc_masters": list(location.master_projects),
        "loc_areas": list(location.areas),
        "loc_official": list(location.official_areas),
    }
