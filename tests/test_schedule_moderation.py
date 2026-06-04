from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.domain import CandidateStatus, SourcePublicationPolicy
from uk_jamaat_directory.ingest.sources.mylocalmasjid import import_mylocalmasjid_bundle, parse_file
from uk_jamaat_directory.models.core import ScheduleCandidate
from uk_jamaat_directory.services.schedule_moderation import approve_candidate

FIXTURES = Path(__file__).resolve().parents[1] / "data/fixtures/mylocalmasjid"


@pytest.mark.asyncio
async def test_approve_candidate_rejects_unknown_policy(db_session: AsyncSession) -> None:
    path = FIXTURES / "sample_export.json"
    bundle = parse_file(path)
    await import_mylocalmasjid_bundle(
        db_session,
        bundle,
        raw_payload=path.read_bytes(),
        fetched_url=f"file://{path}",
        publication_policy=SourcePublicationPolicy.UNKNOWN,
    )
    await db_session.commit()

    candidate = await db_session.scalar(select(ScheduleCandidate).limit(1))
    assert candidate is not None

    with pytest.raises(ValueError, match="public redistribution"):
        await approve_candidate(db_session, candidate.id, actor="test-admin")

    await db_session.refresh(candidate)
    assert candidate.status == CandidateStatus.PENDING
