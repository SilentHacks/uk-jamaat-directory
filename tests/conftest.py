from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.main import create_app

POSTGRES_AVAILABLE = os.environ.get("UK_JAMAAT_TEST_POSTGRES", "0") == "1"


@pytest.fixture
def test_settings() -> Settings:
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://directory:directory@localhost:5432/directory_test",
        ),
    )
    return Settings(
        environment="test",
        allowed_hosts=["test"],
        database_url=database_url,
        test_database_url=database_url,
    )


async def _wait_for_database(database_url: str, attempts: int = 30) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await asyncio.sleep(1)
    await engine.dispose()
    if last_error is not None:
        raise last_error


@pytest.fixture
async def db_engine(test_settings: Settings):
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostGIS tests require UK_JAMAAT_TEST_POSTGRES=1 and a running database.")

    await _wait_for_database(test_settings.database_url)

    engine = create_async_engine(test_settings.database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    env = os.environ.copy()
    env["DATABASE_URL"] = test_settings.database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=env,
        cwd=os.getcwd(),
    )

    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def admin_client_with_db(
    test_settings: Settings,
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    test_settings.admin_api_key = "test-admin-key"
    app = create_app(test_settings)

    async def _override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def client_with_db(
    test_settings: Settings,
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    app = create_app(test_settings)

    async def _override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
