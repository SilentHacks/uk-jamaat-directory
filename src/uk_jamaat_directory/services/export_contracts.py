from __future__ import annotations

import json
from pathlib import Path

from uk_jamaat_directory.api.openapi_public import build_public_openapi
from uk_jamaat_directory.main import create_app
from uk_jamaat_directory.schemas.public import (
    ChangeFeedResponse,
    MosqueDetailPublic,
    MosqueListResponse,
    NearbyTimesResponse,
    SnapshotResponse,
    TimesResponse,
)

PUBLIC_SCHEMA_MODELS = [
    MosqueListResponse,
    MosqueDetailPublic,
    TimesResponse,
    NearbyTimesResponse,
    ChangeFeedResponse,
    SnapshotResponse,
]


def export_openapi(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    app = create_app()
    openapi_path = output_dir / "openapi.json"
    spec = build_public_openapi(app)
    openapi_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return openapi_path


def export_json_schemas(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for model in PUBLIC_SCHEMA_MODELS:
        path = output_dir / f"{model.__name__}.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2), encoding="utf-8")
        written.append(path)
    return written
