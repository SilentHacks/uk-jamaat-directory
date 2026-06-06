"""Tier 1c: Charity Commission for England and Wales bulk register join.

The Charity Commission publishes a daily TSV extract of every registered
charity under the Open Government Licence v3.0. This provider loads that
extract, indexes it by postcode, and for every mosque missing a website
with a known postcode, looks up charities whose name fuzzy-matches the
mosque name and whose postcode is the same.

Each match is written as a synthetic ``SourceType.CHARITY_REGISTER`` row
with ``external_id=charity_number`` and the CC's website. The lead is
flagged with ``linked_source_id`` pointing at that row, so the
verification gate accepts the URL as Charity Commission-linked public
provenance without a network fetch.

Notes
-----
* The CC extract is England and Wales only; Scottish mosques are out of
  scope for this provider (OSCR is a separate, future provider).
* Charity names carry the trust's legal name; we fuzzy-match the
  mosque's normalized name against the charity's name, accept any match
  at the gate's standard 60 threshold, and require the postcode to
  match exactly. This is a strong assertion: same building, same trust.
* The synthetic source row's URL is the CC's ``charity_contact_web``
  field. We do not refetch the charity's website during promotion —
  the CC's data is the citation.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
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


def _matches(mosque: Mosque, charity: CharityRecord) -> float:
    if not mosque.postcode or not charity.postcode:
        return 0.0
    mosque_pc = normalize_postcode(mosque.postcode)
    charity_pc = normalize_postcode(charity.postcode)
    if not mosque_pc or not charity_pc:
        return 0.0
    if mosque_pc.replace(" ", "").upper() != charity_pc.replace(" ", "").upper():
        return 0.0
    return float(
        fuzz.token_set_ratio(
            normalize_mosque_name(mosque.name),
            normalize_mosque_name(charity.name),
        )
    )


async def _existing_charity_sources(
    session: AsyncSession, charity_numbers: list[str]
) -> dict[str, MosqueSource]:
    if not charity_numbers:
        return {}
    stmt = select(MosqueSource).where(
        MosqueSource.source_type == SourceType.CHARITY_REGISTER,
        MosqueSource.external_id.in_(charity_numbers),
    )
    rows = list((await session.execute(stmt)).scalars().all())
    return {row.external_id: row for row in rows}


async def _candidate_mosques_async(session: AsyncSession) -> list[Mosque]:
    stmt = select(Mosque).where(
        (Mosque.website_url.is_(None)) | (Mosque.website_url == ""),
        Mosque.postcode.is_not(None),
    )
    return list((await session.execute(stmt)).scalars().all())


async def _upsert_charity_source(
    session: AsyncSession, charity: CharityRecord, mosque: Mosque
) -> MosqueSource:
    """Write (or reuse) a ``CHARITY_REGISTER`` source row for this charity.

    Idempotent: if a row already exists with the same
    ``(source_type, external_id)``, we reuse it and update only
    ``last_seen_at`` + ``metadata_`` to reflect the latest run.
    """
    existing = (
        await session.execute(
            select(MosqueSource).where(
                MosqueSource.source_type == SourceType.CHARITY_REGISTER,
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
        source_type=SourceType.CHARITY_REGISTER,
        external_id=charity.charity_number,
        source_url=charity.website,
        display_name=charity.name,
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.OFFICIAL_IMPORT,
        attribution="Charity Commission for England and Wales (Open Government Licence v3.0)",
        last_seen_at=datetime.now(UTC),
        metadata_=metadata,
    )
    session.add(source)
    return source


async def propose_charity_commission_leads(
    session: AsyncSession,
    *,
    charity_index: Mapping[str, list[CharityRecord]],
) -> tuple[list[WebsiteLead], WebsiteLeadResult]:
    """Propose Charity Commission website leads for mosques missing a website.

    ``charity_index`` is the postcode-indexed mapping returned by
    :func:`load_charity_index`. Pass it in to keep the I/O (200K rows)
    out of the provider's hot path and to make this function unit-testable.
    """
    result = WebsiteLeadResult()
    leads: list[WebsiteLead] = []
    if not charity_index:
        return leads, result

    mosques = await _candidate_mosques_async(session)
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

    # Eagerly reuse any existing CHARITY_REGISTER source rows so we don't
    # write duplicates.
    existing = await _existing_charity_sources(session, sorted(candidate_numbers))

    for mosque, charity, score in matches:
        source = existing.get(charity.charity_number)
        if source is None:
            source = await _upsert_charity_source(session, charity, mosque)
            existing[charity.charity_number] = source
        url = _normalise_web(charity.website or "")
        assert url is not None
        leads.append(
            WebsiteLead(
                mosque_id=mosque.id,
                url=url,
                provider=WebsiteProvider.CHARITY_COMMISSION,
                reason=f"charity_number_match score={score:.0f}",
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
