from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.ingest.sources.openstreetmap.mapper import (
    MapElementsResult,
    map_overpass_elements,
)
from uk_jamaat_directory.ingest.sources.openstreetmap.query import (
    build_uk_ie_muslim_places_queries,
)
from uk_jamaat_directory.ingest.sources.openstreetmap.schema import OsmImportBundle

OSM_ATTRIBUTION = "© OpenStreetMap contributors (ODbL 1.0)"


@dataclass
class OsmExportResult:
    places_written: int = 0
    places_skipped: int = 0
    skip_reasons: Counter[str] = field(default_factory=Counter)
    output_path: Path | None = None
    dry_run: bool = False


async def export_osm_bundle(
    output_path: Path | None,
    *,
    overpass_url: str | None = None,
    dry_run: bool = False,
    settings: Settings | None = None,
) -> tuple[OsmImportBundle, OsmExportResult]:
    cfg = settings or get_settings()
    url = overpass_url or cfg.osm_overpass_url
    elements: list[dict[str, Any]] = []
    for _region, query in build_uk_ie_muslim_places_queries():
        payload = await _fetch_overpass(
            query,
            url=url,
            timeout_seconds=cfg.osm_overpass_timeout_seconds,
            settings=cfg,
        )
        region_elements = payload.get("elements")
        if not isinstance(region_elements, list):
            msg = "Overpass response missing 'elements' array"
            raise ValueError(msg)
        elements.extend(region_elements)

    mapped = map_overpass_elements(elements)
    bundle = OsmImportBundle(
        format_version="1",
        exported_at=datetime.now(UTC),
        attribution=OSM_ATTRIBUTION,
        places=mapped.places,
    )

    result = OsmExportResult(
        places_written=len(bundle.places),
        places_skipped=sum(mapped.skip_reasons.values()),
        skip_reasons=Counter({key: value for key, value in mapped.skip_reasons.items()}),
        dry_run=dry_run,
    )

    if dry_run:
        return bundle, result

    if output_path is None:
        msg = "output_path is required unless dry_run is set"
        raise ValueError(msg)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result.output_path = output_path
    return bundle, result


def _overpass_headers(settings: Settings) -> dict[str, str]:
    return {
        "User-Agent": settings.crawl_user_agent,
        "Accept": "application/json",
    }


async def _fetch_overpass(
    query: str,
    *,
    url: str,
    timeout_seconds: float,
    settings: Settings | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    timeout = httpx.Timeout(timeout_seconds)
    headers = _overpass_headers(cfg)
    last_error: Exception | None = None

    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
                response = await client.post(url, data={"data": query})
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt == 0:
                await asyncio.sleep(2.0)
                continue
            msg = f"Overpass request failed: {exc}"
            raise RuntimeError(msg) from exc

        if response.status_code == 429:
            msg = "Overpass API rate limited (HTTP 429); retry later"
            raise RuntimeError(msg)
        if response.status_code == 504:
            msg = "Overpass API timed out (HTTP 504); retry later"
            raise RuntimeError(msg)
        if response.status_code >= 500:
            last_error = RuntimeError(f"Overpass API server error (HTTP {response.status_code})")
            if attempt == 0:
                await asyncio.sleep(2.0)
                continue
            raise last_error
        if response.status_code >= 400:
            msg = f"Overpass API request failed (HTTP {response.status_code})"
            raise RuntimeError(msg)

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            msg = "Overpass response was not valid JSON"
            raise RuntimeError(msg) from exc

        if not isinstance(payload, dict):
            msg = "Overpass response JSON must be an object"
            raise ValueError(msg)
        return payload

    if last_error is not None:
        raise last_error
    msg = "Overpass request failed"
    raise RuntimeError(msg)


def build_bundle_from_overpass_payload(
    payload: dict[str, Any],
) -> tuple[OsmImportBundle, MapElementsResult]:
    elements = payload.get("elements")
    if not isinstance(elements, list):
        msg = "Overpass response missing 'elements' array"
        raise ValueError(msg)

    mapped = map_overpass_elements(elements)
    bundle = OsmImportBundle(
        format_version="1",
        exported_at=datetime.now(UTC),
        attribution=OSM_ATTRIBUTION,
        places=mapped.places,
    )
    return bundle, mapped
