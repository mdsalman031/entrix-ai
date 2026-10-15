from __future__ import annotations

import os

# Settings uses standard field-name environment variables (no application
# prefix), so tests cannot accidentally clear a developer's demo database.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test-entrix.db")
os.environ.setdefault("EMBEDDING_BACKEND", "hash")
os.environ.setdefault("QDRANT_IN_MEMORY", "true")

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, async_session_factory, engine


@pytest_asyncio.fixture(autouse=True)
async def clean_database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
        await session.rollback()
