"""Shared logic for UK charity register website discovery providers.

The Charity Commission for England and Wales and the Office of the
Scottish Charity Regulator (OSCR) both publish daily bulk extracts of
their charity registers under the Open Government Licence v3.0. The
discovery providers for both registers share the same flow:

1. Index the register by postcode.
2. For each mosque missing a website with a known postcode, look up
   charities on the same postcode whose name fuzzy-matches the mosque
   name.
3. For each match, write a synthetic source row keyed by
   ``(source_type, external_id=charity_number)`` and propose a
   :class:`WebsiteLead` flagged with that source's ID.

This module exposes :func:`propose_charity_register_leads` which the
two provider wrappers (``charity_commission``, ``oscr``) call with
their own (source type, attribution, provider enum, charity index).
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import (
    Confidence,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.discovery.websites.providers.charity_index import (
    CharityRecord,
)
from uk_jamaat_directory.ingest.discovery.websites.types import (
    WebsiteLead,
    WebsiteLeadResult,
    WebsiteProvider,
)
from uk_jamaat_directory.ingest.normalize import (
    normalize_mosque_name,
    normalize_postcode,
)
from uk_jamaat_directory.models.core import Mosque, MosqueSource

_NAME_RATIO_THRESHOLD = 60.0
_MIN_SHARED_SIGNIFICANT_TOKENS = 2

# Tokens dropped when counting shared mosque/charity name evidence. Keeps
# location words like "broomhouse" while ignoring generic organisational glue.
_SIGNIFICANT_TOKEN_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "for",
        "in",
        "of",
        "the",
        "to",
        "uk",
        "ltd",
        "limited",
        "trust",
        "charity",
        "registered",
    }
)

_DENY_HOST_FRAGMENTS = (
    "register-of-charities.charitycommission.gov.uk",
    "oscr.org.uk",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "linkedin.com",
    "wikipedia.org",
)


@dataclass(frozen=True)
class CharityRegisterConfig:
    """Per-register parameters for the shared provider."""

    source_type: SourceType
    attribution: str
    provider: WebsiteProvider
    reason_prefix: str


def _normalise_web(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    if "://" in text:
        return text
    return f"https://{text}"


def _is_denied_url(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return any(fragment in host for fragment in _DENY_HOST_FRAGMENTS)


def _significant_tokens(name: str) -> set[str]:
    return {
        token
        for token in normalize_mosque_name(name).split()
        if len(token) >= 3 and token not in _SIGNIFICANT_TOKEN_STOP
    }


def _shared_significant_token_count(mosque_name: str, charity_name: str) -> int:
    return len(_significant_tokens(mosque_name) & _significant_tokens(charity_name))


def _matches(mosque: Mosque, charity: CharityRecord) -> float:
    if not mosque.postcode or not charity.postcode:
        return 0.0
    mosque_pc = normalize_postcode(mosque.postcode)
    charity_pc = normalize_postcode(charity.postcode)
    if not mosque_pc or not charity_pc:
        return 0.0
    if mosque_pc.replace(" ", "").upper() != charity_pc.replace(" ", "").upper():
        return 0.0
    if (
        _shared_significant_token_count(mosque.name, charity.name)
        < _MIN_SHARED_SIGNIFICANT_TOKENS
    ):
        return 0.0
    return float(
        fuzz.token_set_ratio(
            normalize_mosque_name(mosque.name),
            normalize_mosque_name(charity.name),
        )
    )


async def _existing_register_sources(
    session: AsyncSession, source_type: SourceType, charity_numbers: list[str]
) -> dict[str, MosqueSource]:
    if not charity_numbers:
        return {}
    stmt = select(MosqueSource).where(
        MosqueSource.source_type == source_type,
        MosqueSource.external_id.in_(charity_numbers),
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return {row.external_id: row for row in rows}


async def _candidate_mosques(session: AsyncSession) -> list[Mosque]:
    stmt = select(Mosque).where(
        (Mosque.website_url.is_(None)) | (Mosque.website_url == ""),
        Mosque.postcode.is_not(None),
    )
    return list((await session.execute(stmt)).scalars().all())


async def _upsert_register_source(
    session: AsyncSession,
    *,
    source_type: SourceType,
    attribution: str,
    charity: CharityRecord,
    mosque: Mosque,
) -> MosqueSource:
    existing = (
        await session.execute(
            select(MosqueSource).where(
                MosqueSource.source_type == source_type,
                MosqueSource.external_id == charity.charity_number,
            )
        )
    ).scalar_one_or_none()

    metadata = {
        "charity_name": charity.name,
        "charity_postcode": charity.postcode,
        "charity_status": charity.status,
        "matched_mosque_id": str(mosque.id),
        "matched_mosque_name": mosque.name,
    }

    if existing is not None:
        existing.last_seen_at = datetime.now(UTC)
        existing.metadata_ = {**(existing.metadata_ or {}), **metadata}
        return existing

    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=source_type,
        external_id=charity.charity_number,
        source_url=charity.website,
        display_name=charity.name,
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.OFFICIAL_IMPORT,
        attribution=attribution,
        last_seen_at=datetime.now(UTC),
        metadata_=metadata,
    )
    session.add(source)
    return source


async def propose_charity_register_leads(
    session: AsyncSession,
    *,
    config: CharityRegisterConfig,
    charity_index: Mapping[str, list[CharityRecord]],
) -> tuple[list[WebsiteLead], WebsiteLeadResult]:
    """Shared implementation for Charity Commission / OSCR providers."""
    result = WebsiteLeadResult()
    leads: list[WebsiteLead] = []
    if not charity_index:
        return leads, result

    mosques = await _candidate_mosques(session)
    if not mosques:
        return leads, result

    matches: list[tuple[Mosque, CharityRecord, float]] = []
    candidate_numbers: set[str] = set()
    for mosque in mosques:
        postcode = mosque.postcode or ""
        key = postcode.replace(" ", "").upper()
        charities = charity_index.get(key, [])
        if not charities:
            continue
        for charity in charities:
            score = _matches(mosque, charity)
            if score < _NAME_RATIO_THRESHOLD:
                continue
            url = _normalise_web(charity.website or "")
            if not url or _is_denied_url(url):
                continue
            if (mosque.website_url or "").strip() == url:
                continue
            matches.append((mosque, charity, score))
            candidate_numbers.add(charity.charity_number)
            result.candidates_proposed += 1

    if not matches:
        return leads, result

    existing = await _existing_register_sources(
        session, config.source_type, sorted(candidate_numbers)
    )

    for mosque, charity, score in matches:
        source = existing.get(charity.charity_number)
        if source is None:
            source = await _upsert_register_source(
                session,
                source_type=config.source_type,
                attribution=config.attribution,
                charity=charity,
                mosque=mosque,
            )
            existing[charity.charity_number] = source
        url = _normalise_web(charity.website or "")
        assert url is not None
        leads.append(
            WebsiteLead(
                mosque_id=mosque.id,
                url=url,
                provider=config.provider,
                reason=f"{config.reason_prefix}_score={score:.0f}",
                matched_postcode=mosque.postcode,
                linked_source_id=source.id,
                extra={
                    "charity_number": charity.charity_number,
                    "charity_name": charity.name,
                    "name_score": f"{score:.0f}",
                },
            )
        )

    return leads, result
