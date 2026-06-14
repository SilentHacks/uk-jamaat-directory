"""Shared domain policy for the extraction pipeline.

Three tiers of third-party domains matter to the authoring pipeline:

* **Aggregators** — mosque directories that publish *calculated* prayer-start
  times, never mosque-confirmed jamaat times. Sources on these domains must
  never be authored against (``failed`` / ``aggregator``).
* **Umbrella sites** — multi-mosque publishers (mosque councils, community
  networks) that *may* carry real jamaat times for member mosques but need a
  human decision first (``skipped_review`` / ``umbrella_review``).
* **Trusted widget hosts** — timetable platforms a mosque deliberately embeds
  on its own site (the mosque configures real jamaat times there). Extractor
  targets on these hosts are allowed even though they are off-domain.

All matching is registrable-domain suffix matching, not exact-host matching.
"""

from __future__ import annotations

from urllib.parse import urlparse

from uk_jamaat_directory.config import Settings

AGGREGATOR_DOMAINS: frozenset[str] = frozenset(
    {
        "praysalat.com",
        "nearestmosque.com",
        "mosquedirectory.co.uk",
        "islamicfinder.org",
        "islamicfinder.com",
        "masjidway.com",
        "masjidway.org",
        "mosquepay.com",
        "alfafaa.com",
        "mosquefinder.com",
        "mosquefinder.co.uk",
        "salah.com",
        "muslimsinbritain.org",
        "mosque.uk",
        "getprayer.com",
        "mosques.org.uk",
        "mosqueradar.com",
        "salahtimes.com",
        "londonprayertimes.com",
    }
)

UMBRELLA_REVIEW_DOMAINS: frozenset[str] = frozenset(
    {
        "towerhamletsmosques.co.uk",
        "ismaili.net",
    }
)

TRUSTED_WIDGET_HOSTS: frozenset[str] = frozenset(
    {
        "mawaqit.net",
        "masjidbox.com",
        "masjidal.com",
        "athanplus.com",
    }
)


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _matches(host_or_domain: str, domains: frozenset[str], extra: list[str] | None) -> bool:
    candidate = host_or_domain.lower().strip(".")
    if not candidate:
        return False
    all_domains = domains if not extra else domains | {d.lower() for d in extra}
    return any(candidate == domain or candidate.endswith(f".{domain}") for domain in all_domains)


def is_aggregator_domain(domain: str | None, *, settings: Settings | None = None) -> bool:
    if not domain:
        return False
    extra = settings.extra_aggregator_domains if settings else None
    return _matches(domain, AGGREGATOR_DOMAINS, extra)


def is_aggregator_url(url: str, *, settings: Settings | None = None) -> bool:
    return is_aggregator_domain(_host_of(url), settings=settings)


def is_umbrella_domain(domain: str | None, *, settings: Settings | None = None) -> bool:
    if not domain:
        return False
    extra = settings.extra_umbrella_domains if settings else None
    return _matches(domain, UMBRELLA_REVIEW_DOMAINS, extra)


def is_umbrella_url(url: str, *, settings: Settings | None = None) -> bool:
    return is_umbrella_domain(_host_of(url), settings=settings)


def is_trusted_widget_url(url: str, *, settings: Settings | None = None) -> bool:
    extra = settings.extra_trusted_widget_hosts if settings else None
    return _matches(_host_of(url), TRUSTED_WIDGET_HOSTS, extra)
