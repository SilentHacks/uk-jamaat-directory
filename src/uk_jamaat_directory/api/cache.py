from __future__ import annotations

from fastapi import Depends, Response


def cache_control(value: str):
    """Return a FastAPI dependency that sets a Cache-Control header on the response.

    Used per-router to make public read endpoints cacheable by browsers, CDNs, and
    well-behaved consumers without coupling the routes to caching infrastructure.
    """

    def _set_cache_control(response: Response) -> None:
        response.headers["Cache-Control"] = value

    return Depends(_set_cache_control)
