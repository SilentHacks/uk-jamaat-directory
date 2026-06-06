"""Verification gate for candidate website URLs.

Moderate strictness: a candidate is promoted to ``mosques.website_url`` when
**either**:

1. the URL was extracted from a public, redistributable source already linked
   to the mosque (MiB, OSM, Charity Commission, Wikidata) — the
   ``linked_source_id`` flag or a matching ``provider`` short-circuits the
   network check; or
2. the live page passes an HTTP + name + (postcode|address) match.

Anything else is returned as an :class:`AdminDiscoveryLead` candidate for an
operator to triage. We never write a URL we did not either find in a public
source or verify live.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser

from rapidfuzz import fuzz

from uk_jamaat_directory.ingest.discovery.websites.types import (
    WebsiteLead,
    WebsiteProvider,
)
from uk_jamaat_directory.ingest.normalize import (
    normalize_mosque_name,
    normalize_postcode,
)
from uk_jamaat_directory.models.core import Mosque

PUBLIC_LINKED_PROVIDERS: frozenset[WebsiteProvider] = frozenset(
    {
        WebsiteProvider.MIB_METADATA,
        WebsiteProvider.OSM_TAG_RECHECK,
        WebsiteProvider.CHARITY_COMMISSION,
        WebsiteProvider.WIKIDATA,
    }
)

# Known directory / aggregator / social platforms: never promote as the mosque
# canonical site. These are common search results and are easy to mistake for
# the mosque's own homepage.
_DIRECTORY_DENY_DOMAINS: frozenset[str] = frozenset(
    {
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
        "twitter.com",
        "www.twitter.com",
        "x.com",
        "instagram.com",
        "www.instagram.com",
        "youtube.com",
        "www.youtube.com",
        "youtu.be",
        "linkedin.com",
        "www.linkedin.com",
        "yell.com",
        "www.yell.com",
        "tripadvisor.com",
        "www.tripadvisor.com",
        "yelp.co.uk",
        "www.yelp.co.uk",
        "google.com",
        "www.google.com",
        "maps.google.com",
        "muslimsinbritain.org",
        "www.muslimsinbritain.org",
        "find-and-update.company-information.service.gov.uk",
        "register-of-charities.charitycommission.gov.uk",
        "oscr.org.uk",
        "www.oscr.org.uk",
        "wikidata.org",
        "www.wikidata.org",
        "wikipedia.org",
        "en.wikipedia.org",
    }
)

_NAME_RATIO_THRESHOLD = 60.0
_PAGE_FETCH_TIMEOUT = 8.0
_PAGE_MAX_BYTES = 1_500_000


@dataclass(frozen=True)
class VerificationOutcome:
    """The result of verifying a single :class:`WebsiteLead`."""

    lead: WebsiteLead
    verified: bool
    name_ratio: float | None
    matched_postcode: bool
    matched_address: bool
    domain_denied: bool
    notes: str


class _TitleAndTextParser(HTMLParser):
    """Extract the first <title> and the visible text from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
        text = data.strip()
        if text:
            self.text_parts.append(text)

    @property
    def title(self) -> str:
        return "".join(self.title_parts).strip()

    @property
    def text(self) -> str:
        return " ".join(self.text_parts)


def _domain_for(url: str) -> str:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def domain_is_denied(url: str) -> bool:
    return _domain_for(url) in _DIRECTORY_DENY_DOMAINS


def _postcode_appears(postcode: str | None, haystack: str) -> bool:
    if not postcode:
        return False
    normalized = normalize_postcode(postcode)
    if not normalized:
        return False
    compact = normalized.replace(" ", "")
    return compact.lower() in haystack.lower().replace(" ", "")


def _address_appears(address: str | None, haystack: str) -> bool:
    if not address:
        return False
    needle = address.strip()
    if len(needle) < 6:
        return False
    return needle.lower() in haystack.lower()


def name_ratio(mosque_name: str, haystack: str) -> float:
    """Return a 0-100 fuzzy match score for the mosque name in the haystack.

    Uses :func:`fuzz.token_set_ratio` so that extra tokens in the haystack
    ("Welcome to the ... & Islamic Centre") do not dilute the score. The
    haystack is the page <title> + first H1 if present + body.
    """
    if not haystack.strip():
        return 0.0
    target = normalize_mosque_name(mosque_name)
    return float(fuzz.token_set_ratio(target, haystack.lower()))


async def _fetch_for_verification(
    url: str, *, user_agent: str, timeout: float
) -> tuple[str, str] | None:
    """Fetch one page. Returns (title, body_text) on success, None on failure.

    Uses a short timeout and a small max-bytes cap to keep the discovery job
    bounded. Failures return None so the caller can treat the candidate as
    not-verified and route it to a discovery lead.
    """
    import httpx

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "text/html,*/*"},
            follow_redirects=True,
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    return None
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type.lower() and "text" not in content_type.lower():
                    return None
                parser = _TitleAndTextParser()
                body_text: list[str] = []
                async for chunk in response.aiter_text():
                    if sum(len(c) for c in body_text) > _PAGE_MAX_BYTES:
                        break
                    body_text.append(chunk)
                    parser.feed(chunk)
                return parser.title, " ".join(body_text)
    except (httpx.HTTPError, ValueError):
        return None


def public_linked_provider(provider: WebsiteProvider) -> bool:
    return provider in PUBLIC_LINKED_PROVIDERS


async def verify_website(
    lead: WebsiteLead,
    mosque: Mosque,
    *,
    user_agent: str,
    timeout: float = _PAGE_FETCH_TIMEOUT,
    fetcher=None,
) -> VerificationOutcome:
    """Verify a single :class:`WebsiteLead` against the moderate policy.

    Parameters
    ----------
    lead
        The candidate URL and the provider that surfaced it.
    mosque
        The mosque row we are trying to attach the URL to.
    user_agent
        Custom UA string sent on the verification fetch.
    timeout
        Per-fetch timeout in seconds.
    fetcher
        Optional async callable ``fetcher(url) -> (title, text) | None`` to
        inject into tests. Production calls use :func:`_fetch_for_verification`.
    """
    if domain_is_denied(lead.url):
        return VerificationOutcome(
            lead=lead,
            verified=False,
            name_ratio=None,
            matched_postcode=False,
            matched_address=False,
            domain_denied=True,
            notes="deny-list domain (directory/aggregator/social)",
        )

    if public_linked_provider(lead.provider) and lead.linked_source_id is not None:
        return VerificationOutcome(
            lead=lead,
            verified=True,
            name_ratio=None,
            matched_postcode=False,
            matched_address=False,
            domain_denied=False,
            notes="public linked source (MiB/OSM/charity/wikidata)",
        )

    fetch = fetcher or (
        lambda u: _fetch_for_verification(u, user_agent=user_agent, timeout=timeout)
    )
    page = await fetch(lead.url)
    if page is None:
        return VerificationOutcome(
            lead=lead,
            verified=False,
            name_ratio=None,
            matched_postcode=False,
            matched_address=False,
            domain_denied=False,
            notes="fetch failed or non-html response",
        )

    title, body = page
    haystack = f"{title}\n{body[:50000]}"
    ratio = name_ratio(mosque.name, haystack)
    matched_postcode = _postcode_appears(mosque.postcode, haystack)
    matched_address = _address_appears(mosque.address_line1, haystack)
    any_contact_match = matched_postcode or matched_address
    verified = ratio >= _NAME_RATIO_THRESHOLD and any_contact_match

    notes = f"name_ratio={ratio:.0f} postcode={matched_postcode} address={matched_address}"
    return VerificationOutcome(
        lead=lead,
        verified=verified,
        name_ratio=ratio,
        matched_postcode=matched_postcode,
        matched_address=matched_address,
        domain_denied=False,
        notes=notes,
    )


def summarize(outcomes: Iterable[VerificationOutcome]) -> dict[str, int]:
    summary: dict[str, int] = {
        "verified": 0,
        "denied": 0,
        "fetch_failed": 0,
        "no_match": 0,
    }
    for outcome in outcomes:
        if outcome.domain_denied:
            summary["denied"] += 1
        elif outcome.verified:
            summary["verified"] += 1
        elif outcome.name_ratio is None:
            summary["fetch_failed"] += 1
        else:
            summary["no_match"] += 1
    return summary
