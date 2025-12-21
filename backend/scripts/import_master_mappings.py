import asyncio
import pandas as pd
from sqlalchemy import text
from backend.app.db.session import async_session
from backend.app.db.models.master_project_mapping import MasterProjectMapping


async def import_master_projects():
    """Import curated master projects from Excel."""
    df = pd.read_excel("master_projects_curated.xlsx")

    async with async_session() as session:
        # Clear existing mappings
        await session.execute(text("DELETE FROM master_project_mappings"))

        # Insert new mappings
        for _, row in df.iterrows():
            if pd.notna(row["display_name"]) and row["display_name"].strip():
                mapping = MasterProjectMapping(
                    display_name=row["display_name"].strip(),
                    search_pattern=row[
                        "display_name"
                    ].strip(),  # Use display name as pattern
                )
                session.add(mapping)

        await session.commit()
        print(f"Imported {len(df)} master project mappings")


if __name__ == "__main__":
    asyncio.run(import_master_projects())
