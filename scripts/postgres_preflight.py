#!/usr/bin/env python3
"""Connectivity probe for PostGIS integration tests (used by make test-postgres-preflight)."""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://directory:directory@localhost:54324/directory_test"
)


async def main() -> None:
    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    finally:
        await engine.dispose()
    print(f"postgres ok: {url}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print(f"postgres probe failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
