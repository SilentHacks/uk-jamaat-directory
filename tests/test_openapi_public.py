from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from uk_jamaat_directory.api.openapi_public import build_public_openapi
from uk_jamaat_directory.config import Environment, Settings
from uk_jamaat_directory.main import create_app


def _public_spec() -> dict:
    app = create_app(Settings(environment=Environment.DEVELOPMENT))
    return build_public_openapi(app)


def test_public_spec_includes_public_routes() -> None:
    spec = _public_spec()
    assert "/v1/mosques" in spec["paths"]
    assert spec["info"]["x-data-license"] == "ODbL-1.0"


def test_public_spec_excludes_admin_routes_and_tag() -> None:
    spec = _public_spec()
    assert not [path for path in spec["paths"] if "/admin" in path]
    for operations in spec["paths"].values():
        for op in operations.values():
            assert "admin" not in op.get("tags", [])


def test_public_spec_has_no_dangling_refs() -> None:
    spec = _public_spec()
    refs = set(re.findall(r"#/components/schemas/([^\"]+)", json.dumps(spec)))
    components = set(spec.get("components", {}).get("schemas", {}).keys())
    assert refs - components == set()


def test_production_serves_public_spec_but_not_internal_docs() -> None:
    app = create_app(Settings(environment=Environment.PRODUCTION, allowed_hosts="testserver"))
    client = TestClient(app)

    spec = client.get("/v1/openapi.json")
    assert spec.status_code == 200
    assert spec.json()["openapi"]
    assert not [path for path in spec.json()["paths"] if "/admin" in path]

    assert client.get("/internal/docs").status_code == 404
    assert client.get("/internal/openapi.json").status_code == 404


def test_development_serves_internal_docs() -> None:
    app = create_app(Settings(environment=Environment.DEVELOPMENT, allowed_hosts="testserver"))
    client = TestClient(app)

    assert client.get("/internal/docs").status_code == 200
    internal = client.get("/internal/openapi.json")
    assert internal.status_code == 200
    # Internal full spec still contains admin routes.
    assert [path for path in internal.json()["paths"] if "/admin" in path]
