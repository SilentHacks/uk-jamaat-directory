"""Tier 1d: Office of the Scottish Charity Regulator (OSCR) bulk register provider.

The Office of the Scottish Charity Regulator publishes a daily CSV
extract of every Scottish registered charity under the Open Government
Licence v3.0. This provider joins that extract against our mosques on
postcode + fuzzy name match, writes a synthetic
``SourceType.OSCR_REGISTER`` source row per match, and proposes a
:class:`WebsiteLead` flagged with that source's ID.

OSCR covers Scotland (postcodes starting EH, FK, G, HS, IV, KA, KW, KY,
ML, PA, PH, TD, ZE, AB, DD, DG). England and Wales are out of scope
(handled by the Charity Commission provider).

The match logic is identical to the Charity Commission provider's;
this module is a thin wrapper around the shared
:mod:`uk_jamaat_directory.ingest.discovery.websites.providers.charity_register`
helper.
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

# The WebsiteProvider enum has a dedicated OSCR slot so the audit log
# can disambiguate Scottish-register matches from England-and-Wales ones.
OSCR_CONFIG = CharityRegisterConfig(
    source_type=SourceType.OSCR_REGISTER,
    attribution=("Office of the Scottish Charity Regulator (Open Government Licence v3.0)"),
    provider=WebsiteProvider.OSCR,
    reason_prefix="oscr_number_match",
)


async def propose_oscr_leads(
    session: AsyncSession,
    *,
    charity_index: Mapping[str, list[CharityRecord]],
) -> tuple[list[WebsiteLead], WebsiteLeadResult]:
    """Propose OSCR website leads for mosques missing a website.

    ``charity_index`` is the postcode-indexed mapping returned by
    :func:`load_oscr_index`. Pass it in to keep the I/O (~25K rows)
    out of the provider's hot path.
    """
    return await propose_charity_register_leads(
        session, config=OSCR_CONFIG, charity_index=charity_index
    )
