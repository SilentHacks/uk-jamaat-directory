from __future__ import annotations

import httpx

ROBOTS_MAX_BYTES = 100_000


async def read_limited_body(
    response: httpx.Response,
    max_bytes: int,
) -> tuple[bytes | None, str | None]:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            return None, f"response exceeds max bytes ({max_bytes})"
        chunks.append(chunk)
    return b"".join(chunks), None
