from __future__ import annotations

import json
from pathlib import Path

from uk_jamaat_directory.services.export_contracts import export_json_schemas, export_openapi


def test_export_contracts_writes_openapi_and_schemas(tmp_path: Path) -> None:
    openapi_path = export_openapi(tmp_path)
    schema_paths = export_json_schemas(tmp_path)

    assert openapi_path.exists()
    openapi_payload = json.loads(openapi_path.read_text(encoding="utf-8"))
    assert "/v1/mosques" in openapi_payload["paths"]
    # Exported contract is the public spec: admin routes are intentionally excluded.
    assert not [path for path in openapi_payload["paths"] if "/admin" in path]

    assert len(schema_paths) == 6
    for path in schema_paths:
        assert path.exists()
        assert "properties" in json.loads(path.read_text(encoding="utf-8"))
