from __future__ import annotations

import re
from urllib.parse import urlparse

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\s]")
_UK_POSTCODE = re.compile(
    r"^([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})$",
    re.IGNORECASE,
)


def normalize_mosque_name(name: str) -> str:
    lowered = name.strip().lower()
    cleaned = _PUNCTUATION.sub(" ", lowered)
    return _WHITESPACE.sub(" ", cleaned).strip()


def normalize_postcode(postcode: str | None) -> str | None:
    if postcode is None:
        return None
    compact = _WHITESPACE.sub("", postcode.strip().upper())
    if len(compact) < 5:
        return compact or None
    outward = compact[:-3]
    inward = compact[-3:]
    normalized = f"{outward} {inward}"
    if _UK_POSTCODE.match(normalized):
        return normalized
    return compact


def normalize_domain(url: str | None) -> str | None:
    if url is None or not url.strip():
        return None
    parsed = urlparse(url.strip() if "://" in url else f"https://{url.strip()}")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_city(city: str | None) -> str | None:
    if city is None:
        return None
    return _WHITESPACE.sub(" ", city.strip().lower()) or None
