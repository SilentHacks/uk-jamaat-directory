from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.main import create_app

# Host port published by docker-compose (54324 avoids common 5432/5433 dev stacks).
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://directory:directory@localhost:54324/directory_test"
)

POSTGRES_AVAILABLE = os.environ.get("UK_JAMAAT_TEST_POSTGRES", "0") == "1"
_DB_WAIT_ATTEMPTS = int(os.environ.get("UK_JAMAAT_TEST_DB_WAIT_ATTEMPTS", "10"))
_DB_WAIT_SECONDS = float(os.environ.get("UK_JAMAAT_TEST_DB_WAIT_SECONDS", "0.5"))


def get_test_database_url() -> str:
    return os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get("DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
    )


@pytest.fixture
def test_settings() -> Settings:
    database_url = get_test_database_url()
    return Settings(
        environment="test",
        allowed_hosts=["test"],
        database_url=database_url,
        test_database_url=database_url,
    )


async def _wait_for_database(database_url: str) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    last_error: Exception | None = None
    for _ in range(_DB_WAIT_ATTEMPTS):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await engine.dispose()
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await asyncio.sleep(_DB_WAIT_SECONDS)
    await engine.dispose()
    if last_error is not None:
        raise last_error


POSTGIS_SYSTEM_TABLES = frozenset(
    {
        "alembic_version",
        "spatial_ref_sys",
        "geometry_columns",
        "geography_columns",
        "raster_columns",
        "raster_overviews",
    }
)


async def _truncate_public_tables(connection) -> None:
    result = await connection.execute(
        text(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            """
        )
    )
    tables = [row[0] for row in result if row[0] not in POSTGIS_SYSTEM_TABLES]
    if not tables:
        return
    table_list = ", ".join(f'"{name}"' for name in tables)
    await connection.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))


async def _bootstrap_schema(database_url: str) -> None:
    await _wait_for_database(database_url)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    await engine.dispose()

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env=env,
        cwd=os.getcwd(),
    )


@pytest.fixture(scope="session")
def postgres_schema_ready() -> str:
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostGIS tests require UK_JAMAAT_TEST_POSTGRES=1 and a running database.")

    database_url = get_test_database_url()
    if os.environ.get("UK_JAMAAT_TEST_REBUILD", "1") == "1":
        asyncio.run(_bootstrap_schema(database_url))
    else:
        asyncio.run(_wait_for_database(database_url))
    return database_url


@pytest_asyncio.fixture
async def db_engine(postgres_schema_ready: str) -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(postgres_schema_ready, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await _truncate_public_tables(session)
        await session.commit()
        yield session


@pytest_asyncio.fixture
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


@pytest_asyncio.fixture
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
