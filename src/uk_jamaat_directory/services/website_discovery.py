"""Phase 5 orchestrator: providers -> verify -> promote | lead.

The orchestrator is the only entry point that writes to the database. It is
deliberately small: gather leads from each provider, verify each lead,
promote the verified ones to ``mosques.website_url`` via a new
``SourceType.MANUAL`` source row (so the change has clean provenance and
shows up in the public source filter), and route the rest to
``AdminDiscoveryLead`` for operator triage.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.domain import (
    Confidence,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.discovery.websites.providers.mib_metadata import (
    propose_mib_metadata_leads,
)
from uk_jamaat_directory.ingest.discovery.websites.providers.osm_tag_recheck import (
    propose_osm_tag_leads,
)
from uk_jamaat_directory.ingest.discovery.websites.types import (
    WebsiteLead,
    WebsiteLeadProvider,
    WebsiteLeadResult,
    WebsiteProvider,
)
from uk_jamaat_directory.ingest.discovery.websites.verify import (
    VerificationOutcome,
    public_linked_provider,
    verify_website,
)
from uk_jamaat_directory.models.core import Mosque, MosqueSource
from uk_jamaat_directory.services.admin_identity import record_discovery_lead


@dataclass
class DiscoveryRunResult:
    providers: dict[str, WebsiteLeadResult] = field(default_factory=dict)
    verified: int = 0
    promoted: int = 0
    denied: int = 0
    fetch_failed: int = 0
    no_match: int = 0
    leads_recorded: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "providers": {k: v.as_dict() for k, v in self.providers.items()},
            "verified": self.verified,
            "promoted": self.promoted,
            "denied": self.denied,
            "fetch_failed": self.fetch_failed,
            "no_match": self.no_match,
            "leads_recorded": self.leads_recorded,
            "errors": list(self.errors),
        }


def _mosque_cache(mosques: Iterable[Mosque]) -> dict[uuid.UUID, Mosque]:
    return {m.id: m for m in mosques}


@dataclass(frozen=True)
class MosqueSnapshot:
    """A pre-flush snapshot of the columns downstream code needs.

    Providers that write auxiliary source rows (e.g. Charity Commission)
    trigger a SQLAlchemy flush which expires cached ``Mosque`` instances.
    Downstream code that reads ``mosque.name`` would then trigger a
    lazy reload, which fails in strict-async mode. We capture the
    columns we need into an immutable snapshot before each provider
    runs and use it instead of the live instance.
    """

    mosque_id: uuid.UUID
    name: str
    postcode: str | None
    website_url: str | None


def _snapshot_mosque(mosque: Mosque) -> MosqueSnapshot:
    return MosqueSnapshot(
        mosque_id=mosque.id,
        name=mosque.name,
        postcode=mosque.postcode,
        website_url=mosque.website_url,
    )


def _snapshot_map(mosques: Iterable[Mosque]) -> dict[uuid.UUID, MosqueSnapshot]:
    return {m.id: _snapshot_mosque(m) for m in mosques}


def _view_mosque(snapshot: MosqueSnapshot) -> Mosque:
    """Build a non-persisted Mosque stub for verify_website.

    The verification gate only reads ``mosque.name``, ``mosque.postcode``,
    and ``mosque.address_line1``. Constructing a fresh ORM instance
    avoids the lazy-reload path on the cached row.
    """
    return Mosque(
        name=snapshot.name,
        normalized_name=snapshot.name.lower(),
        postcode=snapshot.postcode,
        address_line1=None,
    )


async def _select_mosques_missing_website(
    session: AsyncSession,
) -> list[Mosque]:
    stmt = select(Mosque).where((Mosque.website_url.is_(None)) | (Mosque.website_url == ""))
    return list((await session.execute(stmt)).scalars().all())


async def _record_lead(
    session: AsyncSession,
    *,
    lead: WebsiteLead,
    outcome: VerificationOutcome,
    snapshot: MosqueSnapshot,
    actor: str,
) -> None:
    notes = (
        f"provider={lead.provider.value} reason={lead.reason} "
        f"url={lead.url} notes={outcome.notes} "
        f"extra={' '.join(f'{k}={v}' for k, v in lead.extra.items())}"
    )
    await record_discovery_lead(
        session,
        query=f"mosque_id={snapshot.mosque_id}",
        notes=notes,
        location_hint=snapshot.postcode,
        actor=actor,
    )


def _attribution_for(provider: WebsiteProvider) -> str:
    if provider == WebsiteProvider.MIB_METADATA:
        return "MuslimsInBritain.org (detail-page enrichment)"
    if provider == WebsiteProvider.OSM_TAG_RECHECK:
        return "OpenStreetMap contributors"
    if provider == WebsiteProvider.CHARITY_COMMISSION:
        return "Charity Commission for England and Wales"
    if provider == WebsiteProvider.OSCR:
        return "Office of the Scottish Charity Regulator"
    if provider == WebsiteProvider.WIKIDATA:
        return "Wikidata contributors (CC0)"
    if provider == WebsiteProvider.DUCKDUCKGO:
        return "DuckDuckGo search results"
    return f"Phase 5 website discovery ({provider.value})"


async def _promote_website(
    session: AsyncSession,
    *,
    lead: WebsiteLead,
    snapshot: MosqueSnapshot,
    outcome: VerificationOutcome,
) -> bool:
    """Write a new manual source row and set ``mosque.website_url``.

    Idempotency: a source is keyed by ``(source_type, external_id)``; the
    external_id we synthesise is ``f"website-{provider}-{mosque.id}"``. A
    re-run produces a duplicate-key error which we catch inside a nested
    SAVEPOINT so the rest of the session's pending writes (e.g. the
    Charity Commission's auxiliary source rows) are not rolled back.
    """
    from sqlalchemy.exc import IntegrityError

    external_id = f"website-{lead.provider.value}-{snapshot.mosque_id}"
    attribution = _attribution_for(lead.provider)
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=snapshot.mosque_id,
        source_type=SourceType.MANUAL,
        external_id=external_id,
        source_url=lead.url,
        display_name=snapshot.name,
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.VERIFIED,
        attribution=attribution,
        last_seen_at=datetime.now(UTC),
        metadata_={
            "discovery_provider": lead.provider.value,
            "discovery_reason": lead.reason,
            "discovery_verification": outcome.notes,
            "discovery_extra": lead.extra,
        },
    )
    try:
        async with session.begin_nested():
            session.add(source)
    except IntegrityError:
        # already promoted on a previous run; treat as success without
        # rolling back the rest of the session.
        return False

    # Update the live mosque row's website_url. We re-query here so we
    # work against a fresh, non-expired instance regardless of any
    # earlier provider flushes on the same session.
    live = await session.get(Mosque, snapshot.mosque_id)
    if live is not None:
        live.website_url = lead.url
    return True


async def run_website_discovery(
    session: AsyncSession,
    *,
    providers: list[WebsiteLeadProvider] | None = None,
    actor: str = "phase5_discovery",
    user_agent: str | None = None,
) -> DiscoveryRunResult:
    """Run the full discovery + verification + promotion loop.

    ``providers`` defaults to the MiB metadata walk. Other Tier-1 providers
    (OSM re-check, Charity Commission, Wikidata) plug into the same protocol.
    """
    settings = get_settings()
    user_agent = user_agent or settings.crawl_user_agent
    selected = providers or [propose_mib_metadata_leads, propose_osm_tag_leads]

    result = DiscoveryRunResult()
    mosques = await _select_mosques_missing_website(session)
    snapshots = _snapshot_map(mosques)

    outcomes: list[VerificationOutcome] = []
    for provider in selected:
        provider_name = getattr(provider, "__name__", str(provider))
        try:
            leads, provider_result = await provider(session)
        except Exception as exc:  # noqa: BLE001
            result.providers[provider_name] = WebsiteLeadResult(
                candidates_proposed=0, errors=[str(exc)]
            )
            result.errors.append(f"{provider_name}: {exc}")
            continue
        result.providers[provider_name] = provider_result
        for lead in leads:
            snap = snapshots.get(lead.mosque_id)
            if snap is None:
                continue
            # Build a minimal Mosque view for verify_website: name and
            # postcode only. We avoid touching the live instance because
            # a provider's flush may have expired its columns, and a
            # lazy reload fails in strict-async mode.
            verify_mosque = _view_mosque(snap)
            try:
                if public_linked_provider(lead.provider) and lead.linked_source_id is not None:
                    outcome = VerificationOutcome(
                        lead=lead,
                        verified=True,
                        name_ratio=None,
                        matched_postcode=False,
                        matched_address=False,
                        domain_denied=False,
                        notes="public linked source (MiB/OSM/charity/wikidata)",
                    )
                else:
                    outcome = await verify_website(
                        lead, verify_mosque, user_agent=user_agent
                    )
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{lead.url}: {exc}")
                continue

            outcomes.append(outcome)
            if outcome.domain_denied:
                result.denied += 1
                continue
            if outcome.verified:
                result.verified += 1
                promoted = await _promote_website(
                    session, lead=lead, snapshot=snap, outcome=outcome
                )
                if promoted:
                    result.promoted += 1
            else:
                if outcome.name_ratio is None:
                    result.fetch_failed += 1
                else:
                    result.no_match += 1
                await _record_lead(
                    session,
                    lead=lead,
                    outcome=outcome,
                    snapshot=snap,
                    actor=actor,
                )
                result.leads_recorded += 1

    return result
