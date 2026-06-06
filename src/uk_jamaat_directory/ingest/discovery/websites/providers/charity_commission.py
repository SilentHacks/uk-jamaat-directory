"""Tier 1c: Charity Commission for England and Wales bulk register provider.

Thin wrapper around :mod:`uk_jamaat_directory.ingest.discovery.websites.providers.charity_register`
that fixes the source type, attribution, and provider enum to the
Charity Commission values. See that module for the join logic.

The Charity Commission publishes a daily TSV extract of every registered
charity under the Open Government Licence v3.0. We use it as a public,
trustworthy source of UK mosque websites: charities that look like
mosque/masjid/islamic organisations carry a contact website on their
row, and our mosques with matching postcodes + fuzzy name match can
inherit that URL as a low-risk discovery lead.

This provider is England-and-Wales only. Scottish mosques are handled
by :mod:`uk_jamaat_directory.ingest.discovery.websites.providers.oscr`.
"""
from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import SourceType
from uk_jamaat_directory.ingest.discovery.websites.providers.charity_index import (
    CharityRecord,
)
from uk_jamaat_directory.ingest.discovery.websites.providers.charity_register import (
    CharityRegisterConfig,
    propose_charity_register_leads,
)
from uk_jamaat_directory.ingest.discovery.websites.types import (
    WebsiteLead,
    WebsiteLeadResult,
    WebsiteProvider,
)

CC_CONFIG = CharityRegisterConfig(
    source_type=SourceType.CHARITY_REGISTER,
    attribution=(
        "Charity Commission for England and Wales "
        "(Open Government Licence v3.0)"
    ),
    provider=WebsiteProvider.CHARITY_COMMISSION,
    reason_prefix="charity_number_match",
)


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
    return await propose_charity_register_leads(
        session, config=CC_CONFIG, charity_index=charity_index
    )
