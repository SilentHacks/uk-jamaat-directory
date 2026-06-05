from __future__ import annotations

import asyncio
import html
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.ingest.sources.muslimsinbritain.adapter import (
    MIB_BASE_URL,
    MibParsedCsv,
    parse_mib_csv_text,
    validate_mib_bundle,
)
from uk_jamaat_directory.ingest.sources.muslimsinbritain.schema import (
    MibImportBundle,
    MibMosqueRecord,
)

MIB_CSV_URL = "https://mosques.muslimsinbritain.org/gps-csv.php?includecomment=1"
DETAIL_CONCURRENCY = 3
DETAIL_REQUEST_DELAY_SECONDS = 0.35

_LAST_UPDATED = re.compile(r"\bLast\s+Updated:\s*(\d{1,2}/\d{1,2}/\d{4})\b", re.IGNORECASE)
_PHONE = re.compile(
    r"\bPhone:\s*(?P<value>.*?)(?=\s+(?:Website|Affiliation\s+website|Capacity|Theme|Data\s+Accuracy|Notes|Source\(s\)|Last\s+Updated):|$)",
    re.IGNORECASE,
)
_WEBSITE = re.compile(
    r"\b(?:Website|Affiliation\s+website):\s*(?P<value>https?://\S+)",
    re.IGNORECASE,
)
_CAPACITY = re.compile(r"\bCapacity:\s*(?P<value>\d{1,6})\b", re.IGNORECASE)
_THEME = re.compile(
    r"\bTheme:\s*(?P<value>.*?)(?=\s+\1\s*:|\s+Masjid\s+Theme\b|\s+Data\s+Accuracy:|$)",
    re.IGNORECASE,
)
_DATA_ACCURACY = re.compile(
    r"\bData\s+Accuracy:\s*(?P<value>.*?)(?=\s+Some\s+of\s+our\s+address\s+lists\b|\s+Source\(s\):|\s+Last\s+Updated:|$)",
    re.IGNORECASE,
)
_DATA_ACCURACY_CODE = re.compile(r"\(([A-F])\)")
_DATA_SOURCES = re.compile(
    r"\bSource\(s\):\s*(?P<value>.*?)(?=\s+Last\s+Updated:|\s+Provide\s+Feedback\b|$)",
    re.IGNORECASE,
)
_URL_TRAILING_TEXT = re.compile(r"(?=\s+The\s+MuslimsInBritain\.org\s+website\b)", re.IGNORECASE)


@dataclass
class MibExportResult:
    records_written: int = 0
    records_skipped: int = 0
    detail_pages_enriched: int = 0
    detail_pages_failed: int = 0
    skip_reasons: Counter[str] = field(default_factory=Counter)
    output_path: Path | None = None
    source_url: str = MIB_CSV_URL
    dry_run: bool = False


@dataclass(frozen=True)
class MibDetailPage:
    source_record_updated_at: datetime | None = None
    website_url: str | None = None
    phone: str | None = None
    capacity: int | None = None
    theme: str | None = None
    data_accuracy: str | None = None
    data_accuracy_code: str | None = None
    data_sources: list[str] = field(default_factory=list)


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
        enriched, failed = await enrich_mib_details(bundle, settings=cfg)
        result.detail_pages_enriched = enriched
        result.detail_pages_failed = failed
        if failed:
            result.skip_reasons["detail_page_fetch_failed"] += failed
        bundle = validate_mib_bundle(bundle)

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


async def fetch_mib_csv(
    *,
    source_url: str,
    settings: Settings | None = None,
    attempts: int = 3,
) -> str:
    cfg = settings or get_settings()
    headers = {"User-Agent": cfg.crawl_user_agent, "Accept": "text/csv,*/*"}
    timeout = httpx.Timeout(cfg.crawl_timeout_seconds)
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        for attempt in range(attempts):
            try:
                response = await client.get(source_url)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(1.0)
                    continue
                break
            if response.status_code >= 500 and attempt + 1 < attempts:
                await asyncio.sleep(1.0)
                continue
            if response.status_code >= 400:
                msg = f"MiB CSV fetch failed (HTTP {response.status_code})"
                raise RuntimeError(msg)
            return response.text
    msg = "MiB CSV fetch failed"
    if last_error is not None:
        raise RuntimeError(msg) from last_error
    raise RuntimeError(msg)


async def enrich_mib_details(
    bundle: MibImportBundle,
    *,
    settings: Settings | None = None,
    concurrency: int = DETAIL_CONCURRENCY,
    request_delay_seconds: float = DETAIL_REQUEST_DELAY_SECONDS,
) -> tuple[int, int]:
    cfg = settings or get_settings()
    headers = {"User-Agent": cfg.crawl_user_agent, "Accept": "text/html,*/*"}
    timeout = httpx.Timeout(cfg.crawl_timeout_seconds)
    semaphore = asyncio.Semaphore(concurrency)
    enriched = 0
    failed = 0

    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:

        async def enrich_one(record: MibMosqueRecord) -> bool:
            url = record.detail_page_url or _detail_url_for_record(record)
            record.detail_page_url = url
            if url is None:
                return False
            async with semaphore:
                detail = await fetch_mib_detail_page(client, url)
                await asyncio.sleep(request_delay_seconds)
            if detail is None:
                return False
            apply_mib_detail(record, detail)
            return True

        results = await asyncio.gather(*(enrich_one(record) for record in bundle.mosques))

    for ok in results:
        if ok:
            enriched += 1
        else:
            failed += 1
    return enriched, failed


async def fetch_mib_detail_page(
    client: httpx.AsyncClient,
    url: str,
    *,
    attempts: int = 2,
) -> MibDetailPage | None:
    for attempt in range(attempts):
        try:
            response = await client.get(url)
            if response.status_code >= 500 and attempt + 1 < attempts:
                await asyncio.sleep(0.5)
                continue
            if response.status_code >= 400:
                return None
            return parse_mib_detail_page(response.text)
        except httpx.HTTPError:
            if attempt + 1 >= attempts:
                return None
            await asyncio.sleep(0.5)
    return None


def apply_mib_detail(record: MibMosqueRecord, detail: MibDetailPage) -> None:
    if detail.source_record_updated_at is not None:
        record.source_record_updated_at = detail.source_record_updated_at
    if detail.website_url:
        record.website_url = detail.website_url
    if detail.phone:
        record.phone = detail.phone
    if detail.capacity is not None:
        record.capacity = detail.capacity
    if detail.theme:
        record.theme = detail.theme
    if detail.data_accuracy:
        record.data_accuracy = detail.data_accuracy
    if detail.data_accuracy_code:
        record.data_accuracy_code = detail.data_accuracy_code
    if detail.data_sources:
        record.data_sources = detail.data_sources


def parse_mib_detail_page(text: str) -> MibDetailPage:
    plain = _plain_text(text)
    updated_at = _parse_last_updated(plain)
    website_url = _extract_website(plain)
    phone = _clean_field(_regex_value(_PHONE, plain))
    capacity = _parse_int(_regex_value(_CAPACITY, plain))
    theme = _clean_theme(_regex_value(_THEME, plain))
    data_accuracy = _clean_field(_regex_value(_DATA_ACCURACY, plain))
    data_accuracy_code = _extract_data_accuracy_code(data_accuracy)
    data_sources = _parse_sources(_regex_value(_DATA_SOURCES, plain))
    return MibDetailPage(
        source_record_updated_at=updated_at,
        website_url=website_url,
        phone=phone,
        capacity=capacity,
        theme=theme,
        data_accuracy=data_accuracy,
        data_accuracy_code=data_accuracy_code,
        data_sources=data_sources,
    )


def build_bundle_from_mib_csv(text: str) -> MibParsedCsv:
    return parse_mib_csv_text(text)


def _detail_url_for_record(record: MibMosqueRecord) -> str | None:
    raw_id = record.external_id.removeprefix("mib-")
    if not raw_id or not raw_id.isdigit():
        return None
    return f"{MIB_BASE_URL}/show-mosque.php?id={raw_id}&map"


def _plain_text(text: str) -> str:
    text = re.sub(
        r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _regex_value(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return match.group("value")


def _parse_last_updated(text: str) -> datetime | None:
    match = _LAST_UPDATED.search(text)
    if match is None:
        return None
    try:
        return datetime.strptime(match.group(1), "%d/%m/%Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def _extract_website(text: str) -> str | None:
    raw = _regex_value(_WEBSITE, text)
    if raw is None:
        return None
    raw = _URL_TRAILING_TEXT.split(raw, maxsplit=1)[0]
    cleaned = _clean_field(raw)
    if not cleaned:
        return None
    return urljoin(MIB_BASE_URL, cleaned)


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _clean_theme(value: str | None) -> str | None:
    cleaned = _clean_field(value)
    if cleaned is None:
        return None
    # Pages usually repeat the theme immediately before the explanatory paragraph:
    # "Theme: Deobandi Deobandi: Influenced by ...". Keep only the label.
    repeated = re.match(r"(?P<label>[^:]{2,80}?)\s+\1\s*:", cleaned, flags=re.IGNORECASE)
    if repeated:
        return repeated.group("label").strip()
    return cleaned


def _clean_field(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n.,;")
    return cleaned or None


def _extract_data_accuracy_code(data_accuracy: str | None) -> str | None:
    if data_accuracy is None:
        return None
    match = _DATA_ACCURACY_CODE.search(data_accuracy)
    if match is None:
        return None
    return match.group(1)


def _parse_sources(value: str | None) -> list[str]:
    cleaned = _clean_field(value)
    if cleaned is None:
        return []
    return [part.strip() for part in re.split(r"\s*[,;]\s*", cleaned) if part.strip()]
