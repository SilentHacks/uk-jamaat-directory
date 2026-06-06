from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import ExtractionKind
from uk_jamaat_directory.ingest.extract.ai.client import (
    GroqError,
    GroqMessage,
    groq_chat_completion,
)
from uk_jamaat_directory.ingest.extract.ai.fetch_bounded import (
    BoundedPageResult,
    fetch_bounded_pages,
)
from uk_jamaat_directory.ingest.extract.ai.profile import ExtractionProfile
from uk_jamaat_directory.models.core import ExtractionRun, Mosque, MosqueSource


@dataclass
class ProfileResult:
    profile: ExtractionProfile | None = None
    extraction_run_id: uuid.UUID | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_SYSTEM_PROMPT = (
    "You are a reconnaissance assistant for UK mosque websites. "
    "Your job is to inspect a small set of HTML page snippets from a mosque "
    "website and return a strict JSON object describing where prayer timetable "
    "information lives and how it might be extracted.\n\n"
    "Return ONLY a JSON object matching this schema:\n"
    "{\n"
    '  "timetable_url": "string or null",\n'
    '  "asset_type": "html_table|html_list|pdf|image|json_feed|unknown",\n'
    '  "extraction_strategy": "css_selector|llm_structured|pdf_parser|ocr|api_endpoint|unknown",\n'
    '  "css_selector": "string or null",\n'
    '  "date_range_hint": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} or null,\n'
    '  "requires_javascript": true|false,\n'
    '  "requires_pdf_parsing": true|false,\n'
    '  "requires_ocr": true|false,\n'
    '  "prayers_observed": ["FAJR", "DHUHR", "ASR", "MAGHRIB", "ISHA", "JUMUAH"],\n'
    '  "confidence": 0.0 to 1.0,\n'
    '  "review_notes": "string"\n'
    "}\n\n"
    "confidence should reflect how sure you are: >=0.8 if the timetable is clearly "
    "identifiable, lower if ambiguous or missing."
)


def _build_user_prompt(
    mosque: Mosque,
    pages: list[BoundedPageResult],
) -> str:
    parts: list[str] = []
    parts.append(f"Mosque: {mosque.name}")
    if mosque.city:
        parts.append(f"City: {mosque.city}")
    if mosque.postcode:
        parts.append(f"Postcode: {mosque.postcode}")
    parts.append("")

    for page in pages:
        parts.append(f"--- Page: {page.url} ---")
        parts.append(page.body_snippet)
        parts.append("")

    return "\n".join(parts)


async def profile_mosque_website(
    session: AsyncSession,
    source_id: uuid.UUID,
    settings: Settings,
) -> ProfileResult:
    """Run AI reconnaissance on a mosque website source.

    Fetches a bounded set of pages, sends them to Groq, parses the structured
    response into an ``ExtractionProfile``, and updates the source metadata.
    Also creates an ``ExtractionRun`` row for audit.

    Args:
        session: Async SQLAlchemy session.
        source_id: UUID of the ``MOSQUE_WEBSITE`` source to profile.
        settings: Project settings.

    Returns:
        ``ProfileResult`` containing the parsed profile, run ID, and any warnings/errors.
    """
    result = ProfileResult()

    if not settings.ai_profiling_enabled:
        result.warnings.append("ai_profiling_enabled is False; skipping")
        return result

    source = await session.get(MosqueSource, source_id)
    if source is None:
        result.errors.append("source not found")
        return result

    mosque: Mosque | None = None
    if source.mosque_id is not None:
        mosque = await session.get(Mosque, source.mosque_id)
    if mosque is None:
        result.errors.append("source is not linked to a mosque")
        return result

    pages = await fetch_bounded_pages(session, source, settings)
    if not pages:
        result.errors.append("no fetchable HTML pages found for profiling")
        return result

    user_prompt = _build_user_prompt(mosque, pages)
    messages = [
        GroqMessage(role="system", content=_SYSTEM_PROMPT),
        GroqMessage(role="user", content=user_prompt),
    ]

    raw_profile: dict[str, Any] | None = None
    try:
        groq_response = await groq_chat_completion(
            messages,
            model=settings.ai_model,
            response_format={"type": "json_object"},
            settings=settings,
        )
        choice = groq_response.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        if not content:
            raise GroqError("Groq response contained no message content")
        raw_profile = json.loads(content)
    except (GroqError, json.JSONDecodeError) as exc:
        result.errors.append(f"AI profiling failed: {exc}")
        return result

    try:
        profile = ExtractionProfile.model_validate(raw_profile)
    except Exception as exc:
        result.errors.append(f"Profile validation failed: {exc}")
        # Store the raw response anyway for debugging
        profile = ExtractionProfile(
            review_notes=f"Validation error: {exc}; raw: {json.dumps(raw_profile)[:500]}"
        )

    # Determine profile status
    profile_status = "review_needed"
    if profile.confidence >= 0.8 and profile.asset_type != "unknown":
        profile_status = "ready"

    # Update source metadata
    metadata = dict(source.metadata_ or {})
    metadata["extraction_profile"] = profile.model_dump(mode="json")
    metadata["profile_status"] = profile_status
    metadata["profile_model"] = settings.ai_model
    metadata["profiled_at"] = datetime.now(UTC).isoformat()
    metadata["profile_version"] = profile.profile_version
    source.metadata_ = metadata

    # Create extraction run for audit trail
    run = ExtractionRun(
        id=uuid.uuid4(),
        artifact_id=None,
        source_id=source.id,
        kind=ExtractionKind.AI,
        extractor_version=f"groq-{settings.ai_model}/v1",
        status="succeeded" if not result.errors else "failed",
        score=profile.confidence,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        metadata_={
            "pages_fetched": len(pages),
            "pages": [p.url for p in pages],
            "model": settings.ai_model,
            "raw_profile": raw_profile,
            "review_notes": profile.review_notes,
            "warnings": result.warnings,
            "errors": result.errors,
        },
    )
    session.add(run)
    await session.flush()

    result.profile = profile
    result.extraction_run_id = run.id
    return result
