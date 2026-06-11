from __future__ import annotations

import copy
import re
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

# Routes carrying this OpenAPI tag are operator-only and excluded from the public
# spec. The admin router declares tags=["admin"] in api/v1/admin.py, so the tag is
# the single source of truth and survives any future path reshuffle.
ADMIN_TAG = "admin"

_REF_RE = re.compile(r'"#/components/schemas/([^"]+)"')


def _collect_refs(node: Any, found: set[str]) -> None:
    """Walk an arbitrary JSON node collecting referenced schema names."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _collect_refs(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, found)


def _prune_unreferenced_components(spec: dict[str, Any]) -> None:
    """Drop component schemas not transitively reachable from the kept paths.

    Without this, admin-only Pydantic models would remain in components even after
    their operations are removed, leaking internal shapes into the public spec.
    """
    schemas: dict[str, Any] = spec.get("components", {}).get("schemas", {})
    if not schemas:
        return

    reachable: set[str] = set()
    _collect_refs(spec.get("paths", {}), reachable)

    # Transitively expand: a kept schema may reference other schemas.
    queue = list(reachable)
    while queue:
        name = queue.pop()
        schema = schemas.get(name)
        if schema is None:
            continue
        before = set(reachable)
        _collect_refs(schema, reachable)
        queue.extend(reachable - before)

    spec["components"]["schemas"] = {
        name: schema for name, schema in schemas.items() if name in reachable
    }


def build_public_openapi(app: FastAPI) -> dict[str, Any]:
    """Return an OpenAPI spec with admin-tagged operations and their schemas removed."""
    spec = copy.deepcopy(
        get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
    )

    public_paths: dict[str, Any] = {}
    for path, operations in spec.get("paths", {}).items():
        kept = {
            method: op
            for method, op in operations.items()
            if not (isinstance(op, dict) and ADMIN_TAG in op.get("tags", []))
        }
        if kept:
            public_paths[path] = kept
    spec["paths"] = public_paths

    _prune_unreferenced_components(spec)

    spec.setdefault("info", {})["x-data-license"] = "ODbL-1.0"
    return spec
