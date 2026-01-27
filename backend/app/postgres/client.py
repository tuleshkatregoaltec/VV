from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import Optional, AsyncGenerator
import logging
from app.config import settings

logger = logging.getLogger(__name__)

# Global async engine and session factory
_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None


def get_postgres_engine() -> AsyncEngine:
    """Get or create global PostgreSQL async engine."""
    global _engine, _session_factory

    if _engine is None:
        logger.info(
            f"Initializing PostgreSQL engine: {settings.DATABASE_URL.split('@')[1]}"
        )

        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )

        _session_factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        logger.info("PostgreSQL engine initialized")

    return _engine


async def close_postgres() -> None:
    global _engine, _session_factory

    if _engine is not None:
        logger.info("Disposing PostgreSQL engine")
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    get_postgres_engine()
    if _session_factory == None:
        raise RuntimeError("Session Factory does not yet exist")

    async with _session_factory() as session:
        yield session
