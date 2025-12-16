import asyncio
import pandas as pd
from sqlmodel import select
from backend.app.db.session import async_session
from backend.app.db.models import Transaction, RentContract

async def export_master_projects():
    """Export all unique master projects to Excel for manual curation."""
    async with async_session() as session:
        # Get from both tables
        sales_stmt = select(Transaction.master_project_en).distinct()
        rentals_stmt = select(RentContract.master_project_en).distinct()
        
        sales_result = await session.exec(sales_stmt)
        rentals_result = await session.exec(rentals_stmt)
        
        all_projects = set(sales_result.all()) | set(rentals_result.all())
        all_projects = sorted([p for p in all_projects if p])
        
        # Create DataFrame with template columns
        df = pd.DataFrame({
            'raw_project_name': all_projects,
            'display_name': '',  # You'll fill this manually
            'notes': ''
        })
        
        df.to_excel('master_projects_to_curate.xlsx', index=False)
        print(f"Exported {len(all_projects)} projects to master_projects_to_curate.xlsx")

if __name__ == "__main__":
    asyncio.run(export_master_projects())