from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.db.session import create_engine


@asynccontextmanager
async def cli_db_session(settings: Settings) -> AsyncIterator[AsyncSession]:
    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await engine.dispose()
