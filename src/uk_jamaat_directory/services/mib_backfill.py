"""One-shot backfill: promote MiB website fields onto linked mosques.

The historical MiB import path defaulted to ``publication_policy=unknown``, so
``_apply_mosque_fields`` never wrote MiB fields into the public ``mosques``
row even when an MiB source linked to a mosque created from OSM. ADR 0011
flipped the default to ``public_redistribution_allowed`` (2026-06-06), but
existing rows still need the website promotion.

The backfill honours the same ``only_empty=True`` rule as the live import
path: a mosque that already has a website (typically sourced from OSM) is
never overwritten. See ``src/uk_jamaat_directory/ingest/discovery/resolve.py``
for the in-line equivalent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.models.core import Mosque, MosqueSource, SourceType


@dataclass
class MibWebsiteBackfillResult:
    candidates: int = 0
    updated: int = 0
    skipped_already_set: int = 0
    skipped_no_mosque: int = 0
    skipped_no_website_in_metadata: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "candidates": self.candidates,
            "updated": self.updated,
            "skipped_already_set": self.skipped_already_set,
            "skipped_no_mosque": self.skipped_no_mosque,
            "skipped_no_website_in_metadata": self.skipped_no_website_in_metadata,
            "errors": list(self.errors),
        }


def _extract_website(metadata: dict[str, object] | None) -> str | None:
    if not metadata:
        return None
    raw = metadata.get("website_url")
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    return value or None


async def _candidate_mib_sources(session: AsyncSession) -> list[MosqueSource]:
    stmt = (
        select(MosqueSource)
        .where(MosqueSource.source_type == SourceType.MUSLIMSINBRITAIN)
        .where(MosqueSource.metadata_["website_url"].astext.is_not(None))
        .where(MosqueSource.metadata_["website_url"].astext != "")
    )
    return list((await session.execute(stmt)).scalars().all())


async def backfill_mib_websites(
    session: AsyncSession,
    *,
    dry_run: bool = False,
) -> MibWebsiteBackfillResult:
    """Promote MiB ``metadata_.website_url`` onto the linked mosque row.

    Honours the same ``only_empty=True`` rule as the import path: a mosque
    that already has a website is never overwritten. Reports counts so the
    operator can sanity-check the result.
    """
    result = MibWebsiteBackfillResult()
    sources = await _candidate_mib_sources(session)
    result.candidates = len(sources)

    for source in sources:
        try:
            website = _extract_website(source.metadata_)
            if website is None:
                result.skipped_no_website_in_metadata += 1
                continue
            if source.mosque_id is None:
                result.skipped_no_mosque += 1
                continue
            mosque = await session.get(Mosque, source.mosque_id)
            if mosque is None:
                result.skipped_no_mosque += 1
                continue
            if mosque.website_url:
                result.skipped_already_set += 1
                continue
            if dry_run:
                result.updated += 1
                continue
            stmt = (
                update(Mosque)
                .where(Mosque.id == mosque.id, Mosque.website_url.is_(None))
                .values(website_url=website)
                .execution_options(synchronize_session=False)
            )
            outcome = await session.execute(stmt)
            if outcome.rowcount:
                result.updated += 1
            else:
                result.skipped_already_set += 1
        except Exception as exc:  # noqa: BLE001 — operator-facing report
            result.errors.append(f"{source.source_type}:{source.external_id}: {exc}")

    return result
