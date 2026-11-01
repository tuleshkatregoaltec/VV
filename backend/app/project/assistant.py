"""Project comparisons from public catalogue and project services, excluding all assets."""

from app.project import service
from app.project.radar_queries import REELLY_PROJECT_ID_OFFSET
from app.supply import service as supply_service


async def compare_stored_projects(names: list[str]) -> dict:
    projects = []
    for name in names:
        candidates = await supply_service.list_supply_catalogue_projects(
            search=name, limit=5, include_past=True
        )
        exact = [
            item
            for item in candidates.projects
            if item.project_name.casefold().strip() == name.casefold().strip()
        ]
        if len(exact) != 1:
            projects.append(
                {
                    "requested_name": name,
                    "available": False,
                    "reason": "Choose an exact stored catalogue name; no unique match",
                    "candidates": [item.project_name for item in candidates.projects],
                    "matching_count": candidates.total,
                }
            )
            continue
        catalogue = await supply_service.get_supply_catalogue_project(None, exact[0].project_id)
        try:
            detail = await service.get_project_details(
                -(REELLY_PROJECT_ID_OFFSET + exact[0].project_id)
            )
        except Exception:
            detail = None
        project = catalogue.model_dump(
            mode="json",
            include={
                "project_name",
                "developer_name",
                "area_name",
                "sale_status",
                "completion_date",
                "min_price_aed",
                "max_price_aed",
                "units",
                "payment_plan",
            },
        )
        project["unit_types_total"] = len(project["units"])
        project["units"] = project["units"][:20]
        project["payment_steps_total"] = len(project["payment_plan"])
        project["payment_plan"] = project["payment_plan"][:20]
        project |= {
            "available": True,
            "source": "Reelly project catalogue",
            "captured_at": catalogue.source_metadata.get("scraped_at"),
            "construction_progress_pct": detail.percent_completed if detail else None,
            "missing_information": [
                label
                for label, value in (
                    ("unit prices and sizes", catalogue.units),
                    ("payment plans", catalogue.payment_plan),
                    ("construction progress", detail.percent_completed if detail else None),
                    ("scheduled delivery", catalogue.completion_date),
                )
                if value is None or value == []
            ],
        }
        if catalogue.units and not any(
            unit.price_from_aed is not None or unit.price_to_aed is not None
            for unit in catalogue.units
        ):
            project["missing_information"].append("unit prices")
        if catalogue.units and not any(
            unit.area_from_sqft is not None or unit.area_to_sqft is not None
            for unit in catalogue.units
        ):
            project["missing_information"].append("unit sizes")
        projects.append(project)
    return {
        "projects": projects,
        "limitations": [
            "Catalogue starting prices and payment terms are indicative stored developer information, not a live offer.",
            "Construction progress and scheduled delivery are separate fields; a planned date is not proof of completion.",
            "Nearby achieved prices require a separate, explicitly scoped comparable query; project names alone do not prove geographic equivalence.",
            "Missing fields require verification; no documents, brochures or download links are returned.",
            "At most twenty unit types and twenty payment steps per project are shown; total counts state any omitted rows.",
        ],
    }
