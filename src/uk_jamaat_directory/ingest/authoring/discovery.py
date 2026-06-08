"""Deterministic discovery of a prayer-timetable page on a mosque website.

Given a source URL, fetch the page through the existing crawl security stack
(robots-aware, timeouts, size cap) and score same-domain <a href> links for
prayer-time keywords. The best candidate becomes the target URL; if no
candidate exists, fall back to the source URL itself.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import AuthoringTargetKind
from uk_jamaat_directory.ingest.fetch import fetch_url
from uk_jamaat_directory.ingest.normalize import normalize_domain

_PRAYER_KEYWORDS: tuple[str, ...] = (
    "prayer",
    "prayer-times",
    "prayer_times",
    "salah",
    "salat",
    "namaz",
    "timetable",
    "time-table",
    "schedule",
    "calendar",
    "jumuah",
    "jumma",
    "jummah",
    "jumah",
    "fajr",
    "dhuhr",
    "zuhr",
    "zohar",
    "asr",
    "maghrib",
    "isha",
    "jamaat",
    "mosque-times",
    "mosque_times",
    "salat-times",
    "salat_times",
)

_NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "donate",
    "donation",
    "shop",
    "store",
    "cart",
    "checkout",
    "login",
    "signup",
    "register",
    "policy",
    "privacy",
    "terms",
    "contact",
    "imam",
    "team",
    "about",
    "history",
    "gallery",
    "event",
    "news",
    "blog",
    "live",
    "audio",
    "video",
    "facebook",
    "twitter",
    "instagram",
    "youtube",
    "tiktok",
    "whatsapp",
)

_LINK_HREF_RE = re.compile(r"""href\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)
_LINK_TEXT_RE = re.compile(r">\s*([^<>]{1,200})\s*<", re.IGNORECASE)


@dataclass
class ScoredLink:
    url: str
    score: float
    text: str
    matched_keywords: tuple[str, ...] = field(default_factory=tuple)
    negative_keywords: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class DiscoveryResult:
    source_url: str
    discovered_url: str | None
    target_kind: AuthoringTargetKind
    content_type: str | None
    sample_text: str
    sample_html_bytes: int
    candidates: list[ScoredLink]
    error: str | None = None


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._anchors: list[tuple[str, str]] = []
        self._capture_text: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            href: str | None = None
            for key, value in attrs:
                if key.lower() == "href" and value:
                    href = value
                    break
            if href:
                self._capture_text = href
                self._buf = []

    def handle_data(self, data: str) -> None:
        if self._capture_text is not None:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._capture_text is not None:
            text = "".join(self._buf).strip()
            self._anchors.append((self._capture_text, text))
            self._capture_text = None
            self._buf = []


def _parse_anchors(html: str) -> list[tuple[str, str]]:
    parser = _AnchorParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 — be defensive on weird HTML
        return list(parser._anchors)  # type: ignore[attr-defined]
    return list(parser._anchors)


def _html_to_text(html: str, *, max_chars: int) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:max_chars]


def coerce_kind_from_content_type(content_type: str | None) -> AuthoringTargetKind:
    if not content_type:
        return AuthoringTargetKind.UNKNOWN
    primary = content_type.split(";")[0].strip().lower()
    if primary in {"text/html", "application/xhtml+xml"}:
        return AuthoringTargetKind.HTML
    if primary == "application/pdf":
        return AuthoringTargetKind.PDF
    if primary.startswith("image/"):
        return AuthoringTargetKind.IMAGE
    if primary in {"application/json", "text/json"}:
        return AuthoringTargetKind.JSON
    return AuthoringTargetKind.UNKNOWN


def _score_link(
    *,
    url: str,
    text: str,
    base_domain: str,
    settings: Settings,
) -> ScoredLink | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = (parsed.netloc or "").lower()
    if not host:
        return None
    if not (host == base_domain or host.endswith(f".{base_domain}")):
        return None

    haystack = " ".join(
        [
            url.lower(),
            text.lower(),
            parsed.path.lower(),
        ]
    )
    matched = tuple(kw for kw in _PRAYER_KEYWORDS if kw in haystack)
    negative = tuple(kw for kw in _NEGATIVE_KEYWORDS if kw in haystack)
    if not matched and not negative:
        return None
    score = float(len(matched)) * settings.authoring_keyword_boost
    score -= float(len(negative)) * 1.5
    path_depth = max(0, parsed.path.count("/") - 1)
    score -= 0.1 * path_depth
    if score <= 0:
        return None
    return ScoredLink(
        url=url,
        score=score,
        text=text,
        matched_keywords=matched,
        negative_keywords=negative,
    )


def _rank_candidates(
    anchors: Iterable[tuple[str, str]],
    *,
    base_url: str,
    base_domain: str,
    settings: Settings,
    limit: int,
) -> list[ScoredLink]:
    seen: set[str] = set()
    scored: list[ScoredLink] = []
    for href, text in anchors:
        absolute, _frag = urldefrag(urljoin(base_url, href.strip()))
        if not absolute or absolute in seen:
            continue
        seen.add(absolute)
        candidate = _score_link(
            url=absolute,
            text=text,
            base_domain=base_domain,
            settings=settings,
        )
        if candidate is not None:
            scored.append(candidate)
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:limit]


async def discover_timetable_url(
    *,
    source_url: str,
    settings: Settings,
    prior_artifact: object | None = None,
) -> DiscoveryResult:
    """Fetch ``source_url`` and return the best-guess timetable URL.

    The crawl framework does robots, timeout, size, and throttling. We classify
    the kind by Content-Type, score same-domain links for prayer-time
    keywords, and return the highest-scoring candidate (or the source URL
    itself if no candidate scored above zero).
    """

    fetch = await fetch_url(source_url, prior_artifact=prior_artifact, settings=settings)
    if not fetch.ok:
        return DiscoveryResult(
            source_url=source_url,
            discovered_url=None,
            target_kind=AuthoringTargetKind.UNKNOWN,
            content_type=fetch.content_type,
            sample_text="",
            sample_html_bytes=len(fetch.body or b""),
            candidates=[],
            error=fetch.error or f"http {fetch.status_code}",
        )
    body = fetch.body or b""
    html = body.decode("utf-8", errors="replace")
    base_domain = normalize_domain(source_url) or ""
    anchors = _parse_anchors(html)
    candidates = _rank_candidates(
        anchors,
        base_url=source_url,
        base_domain=base_domain,
        settings=settings,
        limit=settings.authoring_max_candidate_links,
    )
    if candidates:
        discovered = candidates[0].url
    else:
        discovered = source_url
    sample_text = _html_to_text(html, max_chars=settings.authoring_max_sample_bytes)
    return DiscoveryResult(
        source_url=source_url,
        discovered_url=discovered,
        target_kind=coerce_kind_from_content_type(fetch.content_type),
        content_type=fetch.content_type,
        sample_text=sample_text,
        sample_html_bytes=len(body),
        candidates=candidates,
        error=None,
    )


def looks_like_javascript_widget(
    *, sample_text: str, sample_html: str
) -> AuthoringTargetKind:
    """Heuristic upgrade from ``html`` to ``rendered_html``.

    The fetch returns ``text/html`` but the body is empty or just a JS
    container, so the runtime would need a browser. We do not have a browser
    yet, so this is the boundary that lands the source on the review queue.
    """

    if not sample_text.strip() and "<script" in sample_html.lower():
        return AuthoringTargetKind.RENDERED_HTML
    return AuthoringTargetKind.HTML


def head_only_kind(url: str, content_type: str | None) -> AuthoringTargetKind:
    """Classify by Content-Type when we have only a HEAD response."""
    return coerce_kind_from_content_type(content_type)
