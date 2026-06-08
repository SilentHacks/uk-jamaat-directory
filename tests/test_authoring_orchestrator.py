from __future__ import annotations

import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import (
    AuthoringTaskStatus,
    Confidence,
    MosqueStatus,
    SourcePublicationPolicy,
    SourceType,
)
from uk_jamaat_directory.ingest.authoring.orchestrator import (
    run_overnight_orchestrator,
)
from uk_jamaat_directory.ingest.fetch.types import FetchResult
from uk_jamaat_directory.models.core import (
    ExtractorAuthoringTask,
    Mosque,
    MosqueSource,
    SourceExtractorAssignment,
)

HTML_PAGE = """
<!doctype html>
<html>
  <body>
    <nav>
      <a href="/">Home</a>
      <a href="/prayer-times">Prayer Times</a>
      <a href="/donate">Donate</a>
    </nav>
  </body>
</html>
"""

PDF_HEAD = FetchResult(
    status_code=200,
    body=b"%PDF-1.4\n%fake pdf body for test purposes\n",
    content_type="application/pdf",
    etag=None,
    last_modified=None,
    unchanged=False,
)

DRAFT_SCRIPT = '''"""Draft authored by stubbed agent for tests."""
from __future__ import annotations

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "test_html_draft"
    version = "2026.06.08.1"

    source_match = SourceMatch(domains=("draft.test",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://draft.test/prayer-times",
            kind=TargetKind.HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        return ExtractorResult(rows=[], no_schedule_reason="dry run")
'''


def _settings(**overrides: Any) -> Settings:
    base = Settings(
        environment="test",
        database_url="postgresql+asyncpg://x/y",
        crawl_enabled=True,
    )
    data = base.model_dump()
    data.update(overrides)
    return Settings(**data)


async def _seed_source(
    session, *, name: str, domain: str, body_kind: str
) -> MosqueSource:
    mosque = Mosque(
        id=uuid.uuid4(),
        name=name,
        normalized_name=name.lower(),
        website_url=f"https://{domain}/",
        status=MosqueStatus.ACTIVE,
    )
    source = MosqueSource(
        id=uuid.uuid4(),
        mosque_id=mosque.id,
        source_type=SourceType.MOSQUE_WEBSITE,
        external_id=f"web-{mosque.id}",
        source_url=f"https://{domain}/",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True, "test_kind": body_kind},
    )
    session.add(mosque)
    session.add(source)
    await session.flush()
    return source


@pytest.mark.asyncio
async def test_orchestrator_skips_pdf_sources(db_session, test_settings) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    pdf_source = await _seed_source(
        db_session,
        name="PDF Masjid",
        domain="pdf.test",
        body_kind="pdf",
    )
    await db_session.flush()

    settings = _settings(
        crawl_enabled=True,
        authoring_per_source_timeout_seconds=30.0,
    )
    with (
        patch(
            "uk_jamaat_directory.ingest.authoring.discovery.fetch_url",
            new=AsyncMock(return_value=PDF_HEAD),
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.is_opencode_available",
            return_value=True,
        ),
    ):
        summary = await run_overnight_orchestrator(
            session=db_session,
            settings=settings,
            concurrency=1,
            dry_run=True,
        )
    await db_session.commit()

    task = (
        await db_session.execute(
            select(ExtractorAuthoringTask).where(
                ExtractorAuthoringTask.source_id == pdf_source.id
            )
        )
    ).scalar_one_or_none()
    assert task is not None
    assert task.status == AuthoringTaskStatus.SKIPPED_REVIEW.value
    assert task.target_kind == "pdf"
    assert summary.skipped_review == 1
    assert summary.deployed == 0


@pytest.mark.asyncio
async def test_orchestrator_writes_draft_for_html_source(
    db_session, test_settings, tmp_path
) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    html_source = await _seed_source(
        db_session,
        name="Draft Masjid",
        domain="draft.test",
        body_kind="html",
    )
    await db_session.flush()

    html_fetch = FetchResult(
        status_code=200,
        body=HTML_PAGE.encode("utf-8"),
        content_type="text/html; charset=utf-8",
        etag=None,
        last_modified=None,
        unchanged=False,
    )
    timetable_fetch = FetchResult(
        status_code=200,
        body=b"<html><body><table><tr><td>placeholder</td></tr></table></body></html>",
        content_type="text/html; charset=utf-8",
        etag=None,
        last_modified=None,
        unchanged=False,
    )

    settings = _settings(
        crawl_enabled=True,
        authoring_per_source_timeout_seconds=30.0,
    )

    from uk_jamaat_directory.ingest.authoring import orchestrator as orch_mod
    from uk_jamaat_directory.ingest.authoring.agent import AgentResult
    from uk_jamaat_directory.ingest.extract.repo_extractors.scripts import (
        __path__ as scripts_pkg_path,
    )

    async def fake_run_authoring_agent(*, prompt: str, settings: Settings, **kwargs: Any):
        return AgentResult(
            text=f"```python\n{DRAFT_SCRIPT}\n```",
            duration_ms=42,
            command="opencode -m test",
            returncode=0,
            stdout_excerpt="ok",
        )

    scripts_pkg_path.append(str(tmp_path))
    try:
        with (
            patch(
                "uk_jamaat_directory.ingest.authoring.discovery.fetch_url",
                new=AsyncMock(side_effect=[html_fetch, timetable_fetch]),
            ),
            patch(
                "uk_jamaat_directory.ingest.authoring.orchestrator.is_opencode_available",
                return_value=True,
            ),
            patch(
                "uk_jamaat_directory.ingest.authoring.orchestrator.run_authoring_agent",
                new=fake_run_authoring_agent,
            ),
            patch.object(
                orch_mod,
                "_scripts_filesystem_path",
                return_value=str(tmp_path),
            ),
        ):
            summary = await run_overnight_orchestrator(
                session=db_session,
                settings=settings,
                source_id=html_source.id,
                concurrency=1,
                dry_run=False,
            )
    finally:
        if str(tmp_path) in scripts_pkg_path:
            scripts_pkg_path.remove(str(tmp_path))
    await db_session.commit()

    task = (
        await db_session.execute(
            select(ExtractorAuthoringTask).where(
                ExtractorAuthoringTask.source_id == html_source.id
            )
        )
    ).scalar_one_or_none()
    assert task is not None
    if task.status not in {
        AuthoringTaskStatus.AWAITING_REVIEW.value,
        AuthoringTaskStatus.DEPLOYED.value,
    }:
        pytest.fail(
            f"unexpected status: {task.status} error={task.error} validation={task.validation_issues}"
        )
    assert task.discovered_url == "https://draft.test/prayer-times"
    assert task.target_kind == "html"
    assert task.extractor_key is not None
    assert (tmp_path / f"{task.extractor_key}.py").exists()
    assert summary.authored + summary.deployed >= 1
    if task.status == AuthoringTaskStatus.DEPLOYED.value:
        assignment = await db_session.get(
            SourceExtractorAssignment, html_source.id
        )
        assert assignment is not None
        assert assignment.extractor_key == "test_html_draft"


@pytest.mark.asyncio
async def test_orchestrator_marks_failed_when_no_opencode(
    db_session, test_settings
) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    source = await _seed_source(
        db_session,
        name="No OpenCode",
        domain="noc.test",
        body_kind="html",
    )
    await db_session.flush()
    fetch = FetchResult(
        status_code=200,
        body=HTML_PAGE.encode("utf-8"),
        content_type="text/html; charset=utf-8",
        etag=None,
        last_modified=None,
        unchanged=False,
    )
    settings = _settings(
        crawl_enabled=True,
        authoring_per_source_timeout_seconds=30.0,
    )
    with (
        patch(
            "uk_jamaat_directory.ingest.authoring.discovery.fetch_url",
            new=AsyncMock(return_value=fetch),
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.is_opencode_available",
            return_value=False,
        ),
    ):
        summary = await run_overnight_orchestrator(
            session=db_session,
            settings=settings,
            source_id=source.id,
            concurrency=1,
            dry_run=True,
        )
    await db_session.commit()

    task = (
        await db_session.execute(
            select(ExtractorAuthoringTask).where(
                ExtractorAuthoringTask.source_id == source.id
            )
        )
    ).scalar_one_or_none()
    assert task is not None
    assert task.status == AuthoringTaskStatus.FAILED.value
    assert "opencode" in (task.error or "")
    assert summary.failed == 1
