from __future__ import annotations

import asyncio
import glob
import os
import types
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
from uk_jamaat_directory.ingest.authoring.authoring_result import AgentReport, AgentResult
from uk_jamaat_directory.ingest.authoring.orchestrator import (
    _scripts_filesystem_path,
    run_overnight_orchestrator,
)
from uk_jamaat_directory.ingest.fetch.types import FetchResult
from uk_jamaat_directory.models.core import (
    ExtractorAuthoringTask,
    Mosque,
    MosqueSource,
    SourceExtractorAssignment,
)

SCRIPTS_DIR = _scripts_filesystem_path()


class _FakeBackend:
    """Stands in for an AgentBackend; always available, never spawns anything."""

    name = "fake"
    binary = "fake-agent"

    def is_available(self) -> bool:
        return True

    def resolve_model(self, settings: Settings) -> str:
        return settings.ai_agent_model or "fake-model"


# Scripts that existed before the test session started. The cleanup helper
# must NEVER touch these: this directory holds real, repo-owned extractor
# scripts, and tests may only delete files they created themselves.
_PREEXISTING_SCRIPTS = frozenset(
    os.path.basename(path) for path in glob.glob(os.path.join(SCRIPTS_DIR, "*.py"))
)


def _cleanup_orphan_scripts() -> None:
    """Remove ``*.py`` files that tests created in the scripts directory."""

    for path in glob.glob(os.path.join(SCRIPTS_DIR, "*.py")):
        name = os.path.basename(path)
        if name == "__init__.py" or name in _PREEXISTING_SCRIPTS:
            continue
        os.unlink(path)


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
    session, *, name: str, domain: str, source_url: str | None = None
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
        source_url=source_url or f"https://{domain}/",
        publication_policy=SourcePublicationPolicy.PUBLIC_REDISTRIBUTION_ALLOWED,
        confidence=Confidence.OFFICIAL_IMPORT,
        metadata_={"crawl_enabled": True},
    )
    session.add(mosque)
    session.add(source)
    await session.flush()
    return source


@pytest.mark.asyncio
async def test_batch_preflight_filters_only_permanent_failures() -> None:
    """The batch filter drops dead/robots sources but keeps reachable and
    transiently-broken ones for the agent phase. DB-free: persistence and the
    network fetch are stubbed."""
    from uk_jamaat_directory.domain import AuthoringTargetKind
    from uk_jamaat_directory.ingest.authoring.discovery import PreFlightResult
    from uk_jamaat_directory.ingest.authoring.orchestrator import (
        OrchestrationSummary,
        _batch_preflight,
    )

    sources = [
        types.SimpleNamespace(id=uuid.uuid4(), source_url=url)
        for url in (
            "https://ok.test",
            "https://dead.test",
            "https://robots.test",
            "https://flaky.test",
        )
    ]

    async def fake_preflight(*, source_url: str, settings: Settings) -> PreFlightResult:
        if "ok.test" in source_url:
            return PreFlightResult(
                source_url, "ok.test", True, 200, "text/html", 100, AuthoringTargetKind.HTML
            )
        if "dead.test" in source_url:
            return PreFlightResult(
                source_url, "dead.test", False, 404, None, 0,
                AuthoringTargetKind.UNKNOWN, error="HTTP 404",
            )
        if "robots.test" in source_url:
            return PreFlightResult(
                source_url, "robots.test", False, None, None, 0,
                AuthoringTargetKind.UNKNOWN, error="robots.txt disallows fetch",
            )
        return PreFlightResult(
            source_url, "flaky.test", False, 503, None, 0,
            AuthoringTargetKind.UNKNOWN, error="HTTP 503",
        )

    persisted: list[tuple[str, str]] = []

    async def fake_persist(*, session_factory, source, error, failure_category, predicted_kind):
        persisted.append((source.source_url, failure_category))

    summary = OrchestrationSummary()
    with (
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.preflight_source",
            new=fake_preflight,
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator._persist_preflight_failure",
            new=fake_persist,
        ),
    ):
        survivors = await _batch_preflight(
            session_factory=None,
            sources=sources,
            settings=Settings(_env_file=None),
            summary=summary,
            progress_lock=asyncio.Lock(),
            on_progress=None,
            concurrency=4,
        )

    assert {s.source_url for s in survivors} == {"https://ok.test", "https://flaky.test"}
    assert summary.preflight_filtered == 2
    assert summary.failed == 2
    assert summary.processed == 2
    assert summary.preflight_done == 4
    assert dict(persisted) == {
        "https://dead.test": "dead_site",
        "https://robots.test": "blocked_robots",
    }
    assert summary.failure_categories == {"dead_site": 1, "blocked_robots": 1}
    assert summary.phase == "authoring"


def _ok_fetch() -> FetchResult:
    return FetchResult(
        status_code=200,
        body=b"<html><body>hello</body></html>",
        content_type="text/html; charset=utf-8",
        etag=None,
        last_modified=None,
        unchanged=False,
    )


@pytest.mark.asyncio
async def test_orchestrator_marks_failed_when_preflight_unreachable(
    db_session, test_settings
) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    source = await _seed_source(db_session, name="Unreachable", domain="unreachable.test")
    await db_session.flush()
    settings = _settings(crawl_enabled=True)

    with patch(
        "uk_jamaat_directory.ingest.authoring.discovery.fetch_url",
        new=AsyncMock(
            return_value=FetchResult(
                status_code=None,
                body=b"",
                content_type=None,
                etag=None,
                last_modified=None,
                unchanged=False,
                error="robots.txt disallows fetch",
            )
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
            select(ExtractorAuthoringTask).where(ExtractorAuthoringTask.source_id == source.id)
        )
    ).scalar_one_or_none()
    assert task is not None
    assert task.status == AuthoringTaskStatus.FAILED.value
    assert "robots" in (task.error or "")
    assert summary.failed == 1


@pytest.mark.asyncio
async def test_orchestrator_marks_skipped_review_when_agent_skips(
    db_session, test_settings
) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    source = await _seed_source(db_session, name="PDF Mosque", domain="pdf.test")
    await db_session.flush()
    settings = _settings(crawl_enabled=True)

    from uk_jamaat_directory.domain import AuthoringTargetKind

    skip_report = AgentReport(
        status="skipped_review",
        target_url="https://pdf.test/timetable.pdf",
        target_kind=AuthoringTargetKind.PDF,
        reason="pdf target — ocr not yet implemented",
    )

    async def fake_run_authoring_agent(
        *, prompt: str, settings: Settings, **kwargs: Any
    ) -> AgentResult:
        return AgentResult(
            text="STATUS=skipped_review\n",
            duration_ms=10,
            command="opencode -m test",
            returncode=0,
            stdout_excerpt="ok",
            report=skip_report,
        )

    with (
        patch(
            "uk_jamaat_directory.ingest.authoring.discovery.fetch_url",
            new=AsyncMock(return_value=_ok_fetch()),
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.get_agent_backend",
            return_value=_FakeBackend(),
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.run_authoring_agent",
            new=fake_run_authoring_agent,
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
            select(ExtractorAuthoringTask).where(ExtractorAuthoringTask.source_id == source.id)
        )
    ).scalar_one_or_none()
    assert task is not None
    assert task.status == AuthoringTaskStatus.SKIPPED_REVIEW.value
    assert task.target_kind == "pdf"
    assert task.discovered_url == "https://pdf.test/timetable.pdf"
    assert "ocr" in (task.error or "")
    assert summary.skipped_review == 1


@pytest.mark.asyncio
async def test_orchestrator_deploys_draft_when_agent_authored(db_session, test_settings) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    _cleanup_orphan_scripts()
    source = await _seed_source(db_session, name="Draft Masjid", domain="draft.test")
    await db_session.flush()
    # The stub draft returns no rows, so the execution smoke test is disabled
    # here; smoke behaviour is covered by its own tests.
    settings = _settings(crawl_enabled=True, authoring_smoke_test_enabled=False)

    # The agent writes the script to the canonical scripts directory
    # under the orchestrator's computed key. The orchestrator reads,
    # validates, and runs ``sync_repo_extractors`` to create the
    # assignment.
    from uk_jamaat_directory.domain import AuthoringTargetKind
    from uk_jamaat_directory.ingest.authoring.orchestrator import (
        _safe_extractor_key,
    )

    expected_key = _safe_extractor_key(f"Draft Masjid_{str(source.id)[:8]}")
    agent_script_path = os.path.join(SCRIPTS_DIR, f"{expected_key}.py")

    async def fake_run_authoring_agent(
        *, prompt: str, settings: Settings, **kwargs: Any
    ) -> AgentResult:
        with open(agent_script_path, "w", encoding="utf-8") as handle:
            handle.write(DRAFT_SCRIPT)
        return AgentResult(
            text="STATUS=authored\n",
            duration_ms=42,
            command="opencode -m test",
            returncode=0,
            stdout_excerpt="ok",
            report=AgentReport(
                status="authored",
                target_url="https://draft.test/prayer-times",
                target_kind=AuthoringTargetKind.HTML,
                script_path=agent_script_path,
            ),
        )

    with (
        patch(
            "uk_jamaat_directory.ingest.authoring.discovery.fetch_url",
            new=AsyncMock(return_value=_ok_fetch()),
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.get_agent_backend",
            return_value=_FakeBackend(),
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.run_authoring_agent",
            new=fake_run_authoring_agent,
        ),
    ):
        summary = await run_overnight_orchestrator(
            session=db_session,
            settings=settings,
            source_id=source.id,
            concurrency=1,
            dry_run=False,
        )
    await db_session.commit()

    task = (
        await db_session.execute(
            select(ExtractorAuthoringTask).where(ExtractorAuthoringTask.source_id == source.id)
        )
    ).scalar_one_or_none()
    assert task is not None
    if task.status != AuthoringTaskStatus.DEPLOYED.value:
        pytest.fail(
            f"unexpected status: {task.status} error={task.error} "
            f"validation={task.validation_issues}"
        )
    assert task.target_kind == "html"
    assert task.discovered_url == "https://draft.test/prayer-times"
    assert summary.deployed == 1

    assignment = await db_session.get(SourceExtractorAssignment, source.id)
    assert assignment is not None
    assert assignment.extractor_key == "test_html_draft"
    _cleanup_orphan_scripts()


@pytest.mark.asyncio
async def test_orchestrator_marks_failed_when_agent_does_not_emit_status(
    db_session, test_settings
) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    source = await _seed_source(db_session, name="No Status", domain="nostatus.test")
    await db_session.flush()
    settings = _settings(crawl_enabled=True)

    async def fake_run_authoring_agent(
        *, prompt: str, settings: Settings, **kwargs: Any
    ) -> AgentResult:
        return AgentResult(
            text="I got distracted and forgot to emit a summary.",
            duration_ms=10,
            command="opencode -m test",
            returncode=0,
            stdout_excerpt="ok",
            report=AgentReport(),
        )

    with (
        patch(
            "uk_jamaat_directory.ingest.authoring.discovery.fetch_url",
            new=AsyncMock(return_value=_ok_fetch()),
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.get_agent_backend",
            return_value=_FakeBackend(),
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.run_authoring_agent",
            new=fake_run_authoring_agent,
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
            select(ExtractorAuthoringTask).where(ExtractorAuthoringTask.source_id == source.id)
        )
    ).scalar_one_or_none()
    assert task is not None
    assert task.status == AuthoringTaskStatus.FAILED.value
    assert "status" in (task.error or "")
    assert summary.failed == 1


@pytest.mark.asyncio
async def test_orchestrator_marks_failed_when_validation_fails(db_session, test_settings) -> None:
    if os.getenv("UK_JAMAAT_TEST_POSTGRES") != "1":
        pytest.skip("PostGIS integration test disabled")
    _cleanup_orphan_scripts()
    source = await _seed_source(db_session, name="Bad Draft", domain="baddraft.test")
    await db_session.flush()
    settings = _settings(crawl_enabled=True)

    from uk_jamaat_directory.domain import AuthoringTargetKind
    from uk_jamaat_directory.ingest.authoring.orchestrator import (
        _safe_extractor_key,
    )

    expected_key = _safe_extractor_key(f"Bad Draft_{str(source.id)[:8]}")
    bad_path = os.path.join(SCRIPTS_DIR, f"{expected_key}.py")

    bad_script = (
        "import os\n"
        "from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (\n"
        "    BaseMosqueWebsiteExtractor,\n"
        ")\n"
        "class Extractor(BaseMosqueWebsiteExtractor):\n"
        "    key = 'bad'\n"
        "    version = '2026.06.08.1'\n"
        "    def extract(self, ctx):\n"
        "        pass\n"
    )

    async def fake_run_authoring_agent(
        *, prompt: str, settings: Settings, **kwargs: Any
    ) -> AgentResult:
        with open(bad_path, "w", encoding="utf-8") as handle:
            handle.write(bad_script)
        return AgentResult(
            text="STATUS=authored\n",
            duration_ms=10,
            command="opencode -m test",
            returncode=0,
            stdout_excerpt="ok",
            report=AgentReport(
                status="authored",
                target_url="https://baddraft.test/prayer-times",
                target_kind=AuthoringTargetKind.HTML,
                script_path=bad_path,
            ),
        )

    with (
        patch(
            "uk_jamaat_directory.ingest.authoring.discovery.fetch_url",
            new=AsyncMock(return_value=_ok_fetch()),
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.get_agent_backend",
            return_value=_FakeBackend(),
        ),
        patch(
            "uk_jamaat_directory.ingest.authoring.orchestrator.run_authoring_agent",
            new=fake_run_authoring_agent,
        ),
    ):
        await run_overnight_orchestrator(
            session=db_session,
            settings=settings,
            source_id=source.id,
            concurrency=1,
            dry_run=False,
        )
    await db_session.commit()

    task = (
        await db_session.execute(
            select(ExtractorAuthoringTask).where(ExtractorAuthoringTask.source_id == source.id)
        )
    ).scalar_one_or_none()
    assert task is not None
    assert task.status == AuthoringTaskStatus.FAILED.value
    assert task.validation_issues
    _cleanup_orphan_scripts()
