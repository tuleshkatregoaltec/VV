import asyncio
from sqlmodel import SQLModel
from app.db.session import engine
from app.db import models  # noqa: F401 - Import to register all models


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    print("All tables created successfully")


if __name__ == "__main__":
    asyncio.run(create_tables())
