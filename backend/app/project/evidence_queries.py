"""Contact-free, exact-name DLD project evidence for client report composition."""

from app.clickhouse import query


async def fetch_project_evidence(names: list[str]) -> list[dict]:
    return await query(
        """SELECT project_id, project_number, project_name_en,
        master_project_en, area_name_en, developer_name, project_status,
        percent_completed, project_end_date, completion_date, no_of_units,
        scraped_at
        FROM ch_projects WHERE lowerUTF8(project_name_en) IN {names:Array(String)}
        ORDER BY project_name_en, project_number LIMIT 12""",
        {"names": [name.lower() for name in names]},
    )
