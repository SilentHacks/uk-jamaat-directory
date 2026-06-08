"""Pre-flight helpers for the overnight extractor authoring orchestrator.

The agent does the actual discovery (it has network access and navigates the
source's registrable domain). All this module does is run a single polite
``fetch_url`` on the source URL to confirm reachability and record the
content type the agent will see first. If the pre-flight fails, the source
is marked failed before the agent runs and the task can be retried.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import AuthoringTargetKind
from uk_jamaat_directory.ingest.fetch import fetch_url
from uk_jamaat_directory.ingest.normalize import normalize_domain

PREDICTED_KINDS: tuple[AuthoringTargetKind, ...] = (
    AuthoringTargetKind.HTML,
    AuthoringTargetKind.PDF,
    AuthoringTargetKind.IMAGE,
    AuthoringTargetKind.JSON,
    AuthoringTargetKind.RENDERED_HTML,
    AuthoringTargetKind.UNKNOWN,
)


@dataclass
class PreFlightResult:
    source_url: str
    domain: str
    reachable: bool
    status_code: int | None
    content_type: str | None
    content_length: int
    predicted_kind: AuthoringTargetKind
    error: str | None = None


def coerce_kind_from_content_type(content_type: str | None) -> AuthoringTargetKind:
    """Best-effort guess from the response's ``Content-Type`` header."""
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


def looks_like_javascript_widget(*, content_type: str | None, body: bytes) -> bool:
    """Heuristic: HTML body that is mostly empty with a script tag suggests a
    JavaScript-rendered page. The agent can still try, but the orchestrator
    flags this up-front so the agent knows to expect a JS-rendered target.
    """

    if content_type is None or not content_type.lower().startswith("text/html"):
        return False
    if not body:
        return True
    text = body.decode("utf-8", errors="replace").lower()
    return "<script" in text and len(text) < 4_000


async def preflight_source(*, source_url: str, settings: Settings) -> PreFlightResult:
    """Run a polite ``fetch_url`` to confirm the source is reachable."""
    domain = normalize_domain(source_url) or ""
    parsed = urlparse(source_url)
    if not parsed.scheme or not parsed.netloc:
        return PreFlightResult(
            source_url=source_url,
            domain=domain,
            reachable=False,
            status_code=None,
            content_type=None,
            content_length=0,
            predicted_kind=AuthoringTargetKind.UNKNOWN,
            error="source url has no scheme or host",
        )

    fetch = await fetch_url(source_url, settings=settings)
    body = fetch.body or b""
    content_type = fetch.content_type
    predicted = coerce_kind_from_content_type(content_type)
    if predicted == AuthoringTargetKind.HTML and looks_like_javascript_widget(
        content_type=content_type, body=body
    ):
        predicted = AuthoringTargetKind.RENDERED_HTML

    if not fetch.ok:
        return PreFlightResult(
            source_url=source_url,
            domain=domain,
            reachable=False,
            status_code=fetch.status_code,
            content_type=content_type,
            content_length=len(body),
            predicted_kind=predicted,
            error=fetch.error or f"http {fetch.status_code}",
        )

    return PreFlightResult(
        source_url=source_url,
        domain=domain,
        reachable=True,
        status_code=fetch.status_code,
        content_type=content_type,
        content_length=len(body),
        predicted_kind=predicted,
    )
