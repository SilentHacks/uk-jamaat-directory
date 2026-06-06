"""Directory aggregator resolver.

When a search engine returns a directory / aggregator page (PraySalat,
NearestMosque, MosqueDirectory, etc.), the real mosque website URL is often
*embedded* in the page HTML. This module recognises known aggregator domains
and extracts the canonical mosque website so it can be verified through the
same rigid gate.

Architecture
------------
* **Generic extractors** run on every page:
  1. JSON-LD structured data (``@type: Place/Organization/MosquePlaceOfWorship`` → ``url``)
  2. ``<a>`` tags whose text contains "official website", "visit website", etc.
* **Domain-specific extractors** run when the hostname matches a known
  aggregator and the generic extractors returned nothing.
* Every extracted URL is **sanity-checked** (must be HTTP/HTTPS, must not
  loop back to the same aggregator domain) before it is returned.

Adding a new aggregator
-------------------------
1. Add the domain to ``_KNOWN_AGGREGATOR_DOMAINS``.
2. Write a small ``_extract_from_<domain>(html) -> str | None`` helper.
3. Register it in ``_DOMAIN_EXTRACTORS``.
4. (Optional) Run the ``analyse-discovery-leads`` CLI to see the domain in the
   top-no-match list and confirm the extractor works.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_KNOWN_AGGREGATOR_DOMAINS: frozenset[str] = frozenset(
    {
        # Prayer times / directory platforms
        "praysalat.com",
        "www.praysalat.com",
        "nearestmosque.com",
        "www.nearestmosque.com",
        "mosquedirectory.co.uk",
        "www.mosquedirectory.co.uk",
        "islamicfinder.org",
        "www.islamicfinder.org",
        "islamicfinder.com",
        "www.islamicfinder.com",
        "masjidway.com",
        "www.masjidway.com",
        "masjidway.org",
        "www.masjidway.org",
        "mosquepay.com",
        "www.mosquepay.com",
        "alfafaa.com",
        "www.alfafaa.com",
        "mosquefinder.com",
        "www.mosquefinder.com",
        "mosquefinder.co.uk",
        "www.mosquefinder.co.uk",
        # UK-specific directories
        "salah.com",
        "www.salah.com",
        "mosques.muslimsinbritain.org",  # MiB sub-pages (already denied at top-level)
        "mosque.uk",
        "www.mosque.uk",
        # Other aggregators seen in search results
        "getprayer.com",
        "www.getprayer.com",
        "mosques.org.uk",
        "www.mosques.org.uk",
    }
)


def is_aggregator_domain(url: str) -> bool:
    """Return True if the URL's hostname is a known directory / aggregator."""
    host = (urlparse(url).hostname or "").lower()
    return host in _KNOWN_AGGREGATOR_DOMAINS


def resolve_directory_url(page_url: str, html_text: str) -> str | None:
    """Try to extract the real mosque website URL from an aggregator page.

    Returns ``None`` when the page is not recognised as an aggregator or
    when no embedded website URL can be found.
    """
    host = (urlparse(page_url).hostname or "").lower()

    # 1. Generic extractors (work on any page)
    result = _extract_jsonld_url(html_text)
    if result:
        return _sanitise(page_url, result)

    result = _extract_website_anchor(html_text)
    if result:
        return _sanitise(page_url, result)

    # 2. Domain-specific extractors
    extractor = _DOMAIN_EXTRACTORS.get(host)
    if extractor:
        result = extractor(html_text)
        if result:
            return _sanitise(page_url, result)

    return None


# ---------------------------------------------------------------------------
# Generic extractors
# ---------------------------------------------------------------------------


def _extract_jsonld_url(html: str) -> str | None:
    """Look for JSON-LD ``<script type="application/ld+json">`` blocks.

    Accepts ``@type`` values that imply a physical place or organisation:
    Place, Organization, LocalBusiness, Mosque, ReligiousOrganization,
    PlaceOfWorship, etc. Returns the first ``url`` field that looks like
    an external website.
    """
    # Match ld+json blocks (non-greedy, tolerate newlines)
    for block in re.finditer(
        r'<script\s+type=["\']application/ld\+json["\']\s*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        raw = block.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        # JSON-LD can be a single object or a list of objects
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            type_val = item.get("@type", "")
            type_names = {type_val} if isinstance(type_val, str) else set(type_val)
            # Accept any type that looks like a place or org
            if type_names & {
                "Place",
                "Organization",
                "LocalBusiness",
                "Mosque",
                "ReligiousOrganization",
                "PlaceOfWorship",
                "MosquePlaceOfWorship",
            }:
                url = item.get("url")
                if isinstance(url, str) and url.startswith("http"):
                    return url
                # Some sites nest under "mainEntity"
                main = item.get("mainEntity")
                if isinstance(main, dict):
                    url = main.get("url")
                    if isinstance(url, str) and url.startswith("http"):
                        return url
    return None


def _extract_website_anchor(html: str) -> str | None:
    """Look for ``<a>`` tags whose text or title suggests an official website.

    Tolerates common phrasing: "official website", "visit website",
    "website", "homepage", "external site".
    """
    # regex that captures the href of an <a> whose text/content contains
    # one of the target phrases. We do a broad scan.
    keywords = [
        "official website",
        "visit website",
        "visit our website",
        "visit site",
        "website",
        "homepage",
        "external site",
        "our site",
    ]
    # Fast path: search for any keyword in the raw HTML
    lowered = html.lower()
    if not any(kw in lowered for kw in keywords):
        return None

    # Use a regex that finds <a ... href="..."> ... </a>
    for match in re.finditer(
        r'<a\s+[^>]*href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        href = match.group(1)
        text = re.sub(r"<[^>]+>", "", match.group(2)).strip().lower()
        for kw in keywords:
            if kw in text:
                return href
    return None


# ---------------------------------------------------------------------------
# Domain-specific extractors
# ---------------------------------------------------------------------------


def _extract_from_islamicfinder(html: str) -> str | None:
    """IslamicFinder mosque pages sometimes have a 'Website' field.

    Pattern observed: a table row or div with label 'Website:' followed by
    an <a> tag.
    """
    # Look for "Website:" or "Official Website" near an <a> tag
    for match in re.finditer(
        r'(?:Website|Official\s*Website)[:\s]*<a\s+[^>]*href=["\'](https?://[^"\']+)["\']',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        return match.group(1)
    return None


def _extract_from_nearestmosque(html: str) -> str | None:
    """NearestMosque pages: look for 'Visit Website' or similar."""
    # Generic anchor extractor usually catches this, but we can be more
    # specific if needed.
    return None


def _extract_from_praysalat(html: str) -> str | None:
    """PraySalat pages: look for external link patterns."""
    # Generic JSON-LD or anchor extractor usually works.
    return None


_DOMAIN_EXTRACTORS: dict[str, callable] = {
    "islamicfinder.org": _extract_from_islamicfinder,
    "www.islamicfinder.org": _extract_from_islamicfinder,
    "islamicfinder.com": _extract_from_islamicfinder,
    "www.islamicfinder.com": _extract_from_islamicfinder,
}


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------


def _sanitise(page_url: str, extracted: str) -> str | None:
    """Sanity-check an extracted URL.

    * Must be absolute HTTP/HTTPS.
    * Must not loop back to the same aggregator domain.
    * Resolve relative URLs against the page URL.
    """
    joined = urljoin(page_url, extracted.strip())
    parsed = urlparse(joined)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.hostname or "").lower()
    page_host = (urlparse(page_url).hostname or "").lower()
    if host == page_host:
        return None  # loops back to the aggregator itself
    return joined
