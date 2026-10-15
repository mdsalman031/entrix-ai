"""SQLAlchemy 2.0 async engine, session factory, and base model.

Uses SQLite for local development with aiosqlite. Switch DATABASE_URL to
a PostgreSQL connection string for production.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    # SQLite needs these for async writes
    **(
        {"connect_args": {"check_same_thread": False}} if "sqlite" in _settings.database_url else {}
    ),
)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency that yields a database session per request."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    if not _settings.auto_create_schema:
        return
    """Create all tables. For development only — use Alembic migrations in production."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
