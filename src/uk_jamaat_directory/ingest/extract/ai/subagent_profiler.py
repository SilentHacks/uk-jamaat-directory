from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import ExtractionKind
from uk_jamaat_directory.ingest.extract.ai.fetch_bounded import (
    BoundedPageResult,
    fetch_bounded_pages,
)
from uk_jamaat_directory.ingest.extract.ai.profile import ExtractionProfile
from uk_jamaat_directory.ingest.extract.ai.progress_tracker import (
    ProfilingRun,
    mark_completed,
    mark_failed,
    next_batch_dir,
    save_run,
)
from uk_jamaat_directory.ingest.extract.ai.subagent_prompt import build_subagent_prompt
from uk_jamaat_directory.models.core import ExtractionRun, Mosque, MosqueSource


@dataclass
class SubagentBatchItem:
    """One item ready for a subagent to analyse."""

    source_id: str
    source_url: str
    mosque_name: str
    city: str | None
    postcode: str | None
    pages: list[BoundedPageResult]
    prompt: str


@dataclass
class BatchPrepareResult:
    batch_dir: str
    items: list[SubagentBatchItem]
    errors: list[str] = field(default_factory=list)


@dataclass
class SubagentResult:
    source_id: str
    raw_response: str
    success: bool
    profile: ExtractionProfile | None = None
    error: str | None = None


async def prepare_batch(
    session: AsyncSession,
    *,
    limit: int = 10,
    force: bool = False,
    settings: Settings,
    run: ProfilingRun | None = None,
) -> BatchPrepareResult:
    """Query the DB for unprofiled sources, fetch bounded pages, and write
    their context files to a batch directory.

    This is the ``prepare`` half of the subagent profiling workflow.
    The caller should then launch one subagent per item, each receiving
    the prompt stored in ``item.prompt``.

    Returns a ``BatchPrepareResult`` with a batch_dir and list of items.
    """
    from sqlalchemy import select as sa_select

    from uk_jamaat_directory.domain import SourceType

    stmt = (
        sa_select(MosqueSource)
        .where(MosqueSource.source_type == SourceType.MOSQUE_WEBSITE)
        .where(MosqueSource.source_url.is_not(None))
    )
    if not force:
        # Skip sources that already have a profile
        stmt = stmt.where(
            ~MosqueSource.metadata_["profile_status"].astext.in_(
                ["ready", "review_needed"]
            )
        )
    stmt = stmt.limit(limit)

    sources = (await session.execute(stmt)).scalars().all()

    batch_dir = next_batch_dir(run) if run else f"data/profiling_batches/tmp_{uuid.uuid4().hex[:8]}"
    dir_path = Path(batch_dir)
    dir_path.mkdir(parents=True, exist_ok=True)

    items: list[SubagentBatchItem] = []
    errors: list[str] = []

    for source in sources:
        mosque: Mosque | None = None
        if source.mosque_id is not None:
            mosque = await session.get(Mosque, source.mosque_id)

        if mosque is None:
            errors.append(f"source {source.id} not linked to a mosque")
            continue

        pages = await fetch_bounded_pages(session, source, settings)
        if not pages:
            errors.append(f"no HTML pages fetched for {source.id}")
            continue

        prompt = build_subagent_prompt(
            mosque_name=mosque.name,
            city=mosque.city,
            postcode=mosque.postcode,
            source_url=source.source_url or "",
            pages=pages,
        )

        item = SubagentBatchItem(
            source_id=str(source.id),
            source_url=source.source_url or "",
            mosque_name=mosque.name,
            city=mosque.city,
            postcode=mosque.postcode,
            pages=pages,
            prompt=prompt,
        )
        items.append(item)

        # Write source context file
        ctx = {
            "source_id": item.source_id,
            "source_url": item.source_url,
            "mosque_name": item.mosque_name,
            "city": item.city,
            "postcode": item.postcode,
            "pages": [
                {
                    "url": p.url,
                    "body_snippet": p.body_snippet,
                    "content_type": p.content_type,
                }
                for p in pages
            ],
            "prompt": prompt,
        }
        (dir_path / f"{item.source_id}.json").write_text(json.dumps(ctx, indent=2))

    # Write manifest
    manifest = {
        "batch_dir": batch_dir,
        "source_ids": [item.source_id for item in items],
    }
    (dir_path / "manifest.json").write_text(json.dumps(manifest, indent=2))

    if run:
        save_run(run)

    return BatchPrepareResult(batch_dir=batch_dir, items=items, errors=errors)


def parse_subagent_response(text: str) -> ExtractionProfile | None:
    """Parse a subagent's response text into an ``ExtractionProfile``.

    Strips markdown code fences if present, then attempts JSON parse
    and Pydantic validation.
    """
    cleaned = text.strip()
    # Strip markdown code fences if present
    if cleaned.startswith("```"):
        first = cleaned.find("\n")
        if first != -1:
            cleaned = cleaned[first + 1 :]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
        elif cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

    # Subagents sometimes emit Python bool/None literals instead of JSON ones.
    # Use word-boundary replacement to avoid corrupting string contents.
    _py_json_fix = re.compile(r"\b(True|False|None)\b")
    cleaned = _py_json_fix.sub(
        lambda m: {"True": "true", "False": "false", "None": "null"}[m.group(1)],
        cleaned,
    )

    try:
        raw = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try extracting the first JSON object from the text
        brace = cleaned.find("{")
        end = cleaned.rfind("}")
        if brace != -1 and end > brace:
            try:
                raw = json.loads(cleaned[brace : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None

    try:
        return ExtractionProfile.model_validate(raw)
    except Exception:
        return None


async def commit_result(
    session: AsyncSession,
    source_id: uuid.UUID,
    raw_response: str,
    *,
    settings: Settings,
    run: ProfilingRun | None = None,
) -> SubagentResult:
    """Validate a subagent response and write the result to the DB.

    Returns a ``SubagentResult`` with the parsed profile or error message.
    """
    profile = parse_subagent_response(raw_response)

    if profile is None:
        result = SubagentResult(
            source_id=str(source_id),
            raw_response=raw_response,
            success=False,
            error="Failed to parse subagent response as valid ExtractionProfile JSON",
        )
        if run:
            mark_failed(run, str(source_id), result.error)
        return result

    source = await session.get(MosqueSource, source_id)
    if source is None:
        result = SubagentResult(
            source_id=str(source_id),
            raw_response=raw_response,
            success=False,
            error="Source not found",
        )
        return result

    # Determine profile status
    profile_status = "review_needed"
    if profile.confidence >= 0.8 and profile.asset_type != "unknown":
        profile_status = "ready"

    # Update source metadata
    metadata = dict(source.metadata_ or {})
    metadata["extraction_profile"] = profile.model_dump(mode="json")
    metadata["profile_status"] = profile_status
    metadata["profile_model"] = "deepseek-v4-flash"  # the subagent model
    metadata["profiled_at"] = datetime.now(UTC).isoformat()
    metadata["profile_version"] = profile.profile_version
    source.metadata_ = metadata

    # Create extraction run
    run_row = ExtractionRun(
        id=uuid.uuid4(),
        artifact_id=None,
        source_id=source.id,
        kind=ExtractionKind.AI,
        extractor_version="subagent-deepseek-v4-flash/v1",
        status="succeeded",
        score=profile.confidence,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        metadata_={
            "model": "deepseek-v4-flash",
            "raw_profile": raw_response,
            "review_notes": profile.review_notes,
            "profile_status": profile_status,
        },
    )
    session.add(run_row)
    await session.flush()

    result = SubagentResult(
        source_id=str(source_id),
        raw_response=raw_response,
        success=True,
        profile=profile,
    )
    if run:
        mark_completed(run, str(source_id))
        save_run(run)

    return result
