"""Tier 1a: walk MuslimsInBritain source ``metadata_`` for unrecognised
homepage fields and propose them as website leads.

MiB detail-page enrichment records several fields that are not the canonical
``website_url`` (e.g. ``detail_page_url``, ``source_url``, an external
``homepage`` if the upstream directory listed one). The backfill only
promotes ``website_url`` — this provider catches the rest without any
network call.

Leads produced here are flagged with ``mib_source_id`` so the verification
gate accepts them as MiB-linked public provenance.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourceType
from uk_jamaat_directory.ingest.discovery.websites.types import (
    WebsiteLead,
    WebsiteLeadResult,
    WebsiteProvider,
)
from uk_jamaat_directory.models.core import Mosque, MosqueSource

# Keys in MiB source.metadata_ that are likely to be the mosque's own homepage
# (not a directory, detail page, or source URL).
HOMEPAGE_KEYS: tuple[str, ...] = (
    "homepage",
    "homepage_url",
    "mosque_website",
    "official_website",
    "primary_website",
    "url",
)

# Keys that are *not* the mosque's own homepage even if they look like a URL.
NON_HOMEPAGE_KEYS: frozenset[str] = frozenset(
    {
        "website_url",  # already promoted by the backfill
        "detail_page_url",
        "source_url",
        "source_record_url",
        "source_page",
        "source_exported_at",
    }
)


def _candidate_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not text.lower().startswith(("http://", "https://")):
        return None
    return text


async def _load_target_mosques(
    session: AsyncSession,
) -> list[Mosque]:
    stmt = select(Mosque).where((Mosque.website_url.is_(None)) | (Mosque.website_url == ""))
    return list((await session.execute(stmt)).scalars().all())


async def _mib_sources_for(session: AsyncSession, mosque_id: uuid.UUID) -> list[MosqueSource]:
    stmt = select(MosqueSource).where(
        MosqueSource.mosque_id == mosque_id,
        MosqueSource.source_type == SourceType.MUSLIMSINBRITAIN,
    )
    return list((await session.execute(stmt)).scalars().all())


async def propose_mib_metadata_leads(
    session: AsyncSession,
) -> tuple[list[WebsiteLead], WebsiteLeadResult]:
    """Walk MiB source metadata for homepage-like fields.

    Returns the list of leads and a summary result. Order: one lead per
    (mosque, source, key) tuple to keep the trace explicit. The verification
    gate will short-circuit MiB-linked leads.
    """
    result = WebsiteLeadResult()
    leads: list[WebsiteLead] = []
    mosques = await _load_target_mosques(session)
    for mosque in mosques:
        sources = await _mib_sources_for(session, mosque.id)
        for source in sources:
            metadata = source.metadata_ or {}
            for key, value in metadata.items():
                if key in NON_HOMEPAGE_KEYS:
                    continue
                if HOMEPAGE_KEYS and key not in HOMEPAGE_KEYS:
                    continue
                url = _candidate_url(value)
                if not url:
                    continue
                leads.append(
                    WebsiteLead(
                        mosque_id=mosque.id,
                        url=url,
                        provider=WebsiteProvider.MIB_METADATA,
                        reason=f"mib_metadata_{key}",
                        matched_postcode=mosque.postcode,
                        mib_source_id=source.id,
                        extra={"mib_external_id": source.external_id},
                    )
                )
                result.candidates_proposed += 1
    return leads, result
