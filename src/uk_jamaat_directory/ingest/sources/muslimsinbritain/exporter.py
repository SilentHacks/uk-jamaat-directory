from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.ingest.sources.muslimsinbritain.adapter import (
    MibParsedCsv,
    parse_mib_csv_text,
    validate_mib_bundle,
)
from uk_jamaat_directory.ingest.sources.muslimsinbritain.schema import MibImportBundle

MIB_CSV_URL = "https://mosques.muslimsinbritain.org/gps-csv.php?includecomment=1"


@dataclass
class MibExportResult:
    records_written: int = 0
    records_skipped: int = 0
    skip_reasons: Counter[str] = field(default_factory=Counter)
    output_path: Path | None = None
    source_url: str = MIB_CSV_URL
    dry_run: bool = False


async def export_mib_bundle(
    output_path: Path | None,
    *,
    source_url: str = MIB_CSV_URL,
    dry_run: bool = False,
    enrich_details: bool = False,
    settings: Settings | None = None,
) -> tuple[MibImportBundle, MibExportResult]:
    cfg = settings or get_settings()
    csv_text = await fetch_mib_csv(source_url=source_url, settings=cfg)
    parsed = build_bundle_from_mib_csv(csv_text)
    bundle = validate_mib_bundle(parsed.bundle)
    result = MibExportResult(
        records_written=len(bundle.mosques),
        records_skipped=parsed.skipped,
        skip_reasons=Counter(parsed.skip_reasons),
        source_url=source_url,
        dry_run=dry_run,
    )

    if enrich_details:
        # The live CSV already carries coordinates, display metadata, postcode,
        # phone and stable IDs. Detail-page enrichment can be added when a
        # missing field justifies the extra site load.
        result.skip_reasons["detail_enrichment_deferred"] += 0

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


async def fetch_mib_csv(*, source_url: str, settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    headers = {"User-Agent": cfg.crawl_user_agent, "Accept": "text/csv,*/*"}
    timeout = httpx.Timeout(cfg.crawl_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        response = await client.get(source_url)
    if response.status_code >= 400:
        msg = f"MiB CSV fetch failed (HTTP {response.status_code})"
        raise RuntimeError(msg)
    return response.text


def build_bundle_from_mib_csv(text: str) -> MibParsedCsv:
    return parse_mib_csv_text(text)
