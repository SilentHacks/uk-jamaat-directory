"""Tier 1b: re-check OSM source ``metadata_.website_tags`` for alternate
website URLs that the original import did not promote to ``mosque.website_url``.

OSM mappers often carry three website-shaped tags: ``website``,
``contact:website``, and ``url``. The import path only writes one of them
(the canonical ``website_url``). This provider inspects the full set kept
on the source row, joins to the linked mosque, and proposes any URL that
differs from the current ``mosque.website_url``.

The OSM source is a public-licence row (ODbL 1.0), so the leads are
flagged with ``linked_source_id`` and the verification gate accepts them
without a network fetch.
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
    """Load every mosque.

    We do not pre-filter by ``website_url IS NULL`` here: this provider
    compares the source's stored tags against the current value and only
    proposes a lead for URLs that differ. A mosque that already has a
    website may still have additional OSM website tags worth surfacing.
    """
    stmt = select(Mosque)
    return list((await session.execute(stmt)).scalars().all())


async def _osm_sources_for(session: AsyncSession, mosque_id: uuid.UUID) -> list[MosqueSource]:
    stmt = select(MosqueSource).where(
        MosqueSource.mosque_id == mosque_id,
        MosqueSource.source_type == SourceType.OPENSTREETMAP,
    )
    return list((await session.execute(stmt)).scalars().all())


def _extract_website_tags(metadata: dict[str, object] | None) -> list[str]:
    if not metadata:
        return []
    raw = metadata.get("website_tags")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for value in raw:
        url = _candidate_url(value)
        if url:
            out.append(url)
    return out


async def propose_osm_tag_leads(
    session: AsyncSession,
) -> tuple[list[WebsiteLead], WebsiteLeadResult]:
    """Walk OSM sources for alternate website URLs.

    For each mosque missing a website, look up its OSM source rows and
    read ``metadata.website_tags``. Each URL that is not the existing
    ``mosque.website_url`` is proposed as a lead. The verification gate
    short-circuits these as OSM-linked public provenance.
    """
    result = WebsiteLeadResult()
    leads: list[WebsiteLead] = []
    mosques = await _load_target_mosques(session)
    for mosque in mosques:
        existing = (mosque.website_url or "").strip()
        sources = await _osm_sources_for(session, mosque.id)
        for source in sources:
            tags = _extract_website_tags(source.metadata_)
            for url in tags:
                if url == existing:
                    continue
                leads.append(
                    WebsiteLead(
                        mosque_id=mosque.id,
                        url=url,
                        provider=WebsiteProvider.OSM_TAG_RECHECK,
                        reason="osm_website_tag",
                        matched_postcode=mosque.postcode,
                        linked_source_id=source.id,
                        extra={"osm_external_id": source.external_id},
                    )
                )
                result.candidates_proposed += 1
    return leads, result
