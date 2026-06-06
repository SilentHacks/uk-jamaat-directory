from __future__ import annotations

import re
from urllib.parse import urlparse

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w\s]")
_UK_POSTCODE = re.compile(
    r"^([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})$",
    re.IGNORECASE,
)
_EIRCODE = re.compile(
    r"^([A-Z0-9]{3})\s*([A-Z0-9]{4})$",
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
    eircode_match = _EIRCODE.match(compact)
    if eircode_match:
        return f"{eircode_match.group(1)} {eircode_match.group(2)}"
    return compact


def normalize_domain(url: str | None) -> str | None:
    if url is None or not url.strip():
        return None
    parsed = urlparse(url.strip() if "://" in url else f"https://{url.strip()}")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def canonical_homepage(url: str | None) -> str | None:
    if url is None or not url.strip():
        return None
    parsed = urlparse(url.strip() if "://" in url else f"https://{url.strip()}")
    scheme = parsed.scheme or "https"
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    path = parsed.path.rstrip("/") or "/"
    return f"{scheme}://{host}{path}"


def normalize_city(city: str | None) -> str | None:
    if city is None:
        return None
    return _WHITESPACE.sub(" ", city.strip().lower()) or None
