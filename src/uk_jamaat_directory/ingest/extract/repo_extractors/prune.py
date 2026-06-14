"""Prune the existing extractor scripts against the hardened pipeline rules.

Buckets:

* **aggregator** — any target URL on a pure aggregator domain: delete the
  script, retire the assignment, mark the task failed/``aggregator``.
* **umbrella** — any target URL on a multi-mosque umbrella domain: delete
  the script, retire the assignment, mark the task
  ``skipped_review``/``umbrella_review`` (manual review queue).
* **orphan** — script with no active assignment: delete it and reset the
  task to a retryable failure so the new pipeline re-authors it.
* **deployed** — smoke-test the script; failures are deleted and reset to
  retryable, passers are kept (smoke report stamped on the task).
* **broken** — module fails to import: treated like an orphan.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import pkgutil
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.config import Settings, get_settings
from uk_jamaat_directory.domain import AuthoringFailureCategory, AuthoringTaskStatus
from uk_jamaat_directory.ingest.domain_policy import is_aggregator_url, is_umbrella_url
from uk_jamaat_directory.ingest.extract.repo_extractors.registry import (
    RegisteredExtractor,
    load_all_extractors,
)
from uk_jamaat_directory.models.core import (
    ExtractorAuthoringTask,
    MosqueSource,
    SourceExtractorAssignment,
)

logger = logging.getLogger(__name__)

_SCRIPT_PACKAGE = "uk_jamaat_directory.ingest.extract.repo_extractors.scripts"

#: scripts that are test fixtures / not real extractors
_IGNORED_MODULES = {"synthetic_html_table"}


@dataclass
class PruneReport:
    kept: list[str] = field(default_factory=list)
    deleted_aggregator: list[str] = field(default_factory=list)
    deleted_umbrella: list[str] = field(default_factory=list)
    deleted_orphan: list[str] = field(default_factory=list)
    deleted_smoke_failed: dict[str, list[str]] = field(default_factory=dict)
    deleted_broken: list[str] = field(default_factory=list)
    applied: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "kept": sorted(self.kept),
            "deleted_aggregator": sorted(self.deleted_aggregator),
            "deleted_umbrella": sorted(self.deleted_umbrella),
            "deleted_orphan": sorted(self.deleted_orphan),
            "deleted_smoke_failed": {k: v for k, v in sorted(self.deleted_smoke_failed.items())},
            "deleted_broken": sorted(self.deleted_broken),
            "counts": {
                "kept": len(self.kept),
                "aggregator": len(self.deleted_aggregator),
                "umbrella": len(self.deleted_umbrella),
                "orphan": len(self.deleted_orphan),
                "smoke_failed": len(self.deleted_smoke_failed),
                "broken": len(self.deleted_broken),
            },
        }


def _module_file(module_name: str) -> str | None:
    spec = importlib.util.find_spec(module_name)
    return spec.origin if spec and spec.origin else None


def _scripts_dir() -> str:
    package = importlib.import_module(_SCRIPT_PACKAGE)
    return os.path.dirname(package.__file__ or "")


def _broken_module_names(loaded: list[RegisteredExtractor]) -> list[str]:
    loaded_modules = {entry.module_name.rsplit(".", 1)[-1] for entry in loaded}
    package = importlib.import_module(_SCRIPT_PACKAGE)
    broken = []
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_") or info.name in _IGNORED_MODULES:
            continue
        if info.name not in loaded_modules:
            broken.append(info.name)
    return broken


async def _task_for_key(session: AsyncSession, extractor_key: str) -> ExtractorAuthoringTask | None:
    return (
        (
            await session.execute(
                select(ExtractorAuthoringTask).where(
                    ExtractorAuthoringTask.extractor_key == extractor_key
                )
            )
        )
        .scalars()
        .first()
    )


def _reset_task(
    task: ExtractorAuthoringTask | None,
    *,
    status: str,
    category: str | None,
    error: str,
) -> None:
    if task is None:
        return
    task.status = status
    task.failure_category = category
    task.error = error
    task.attempts = 0
    task.script_path = None
    task.finished_at = datetime.now(UTC)


async def _delete_script(
    session: AsyncSession,
    *,
    entry_key: str,
    module_name: str,
    apply: bool,
    status: str,
    category: str | None,
    error: str,
) -> None:
    if not apply:
        return
    path = _module_file(module_name)
    if path and os.path.isfile(path):
        os.unlink(path)
    assignment = (
        (
            await session.execute(
                select(SourceExtractorAssignment).where(
                    SourceExtractorAssignment.extractor_key == entry_key
                )
            )
        )
        .scalars()
        .first()
    )
    if assignment is not None:
        assignment.status = "retired"
    _reset_task(
        await _task_for_key(session, entry_key),
        status=status,
        category=category,
        error=error,
    )


async def prune_repo_extractors(
    session: AsyncSession,
    *,
    settings: Settings | None = None,
    apply: bool = False,
    run_smoke: bool = True,
    concurrency: int = 4,
) -> PruneReport:
    cfg = settings or get_settings()
    report = PruneReport(applied=apply)
    entries = load_all_extractors(reload=True)

    # Broken (unimportable) scripts.
    for name in _broken_module_names(entries):
        report.deleted_broken.append(name)
        if apply:
            path = os.path.join(_scripts_dir(), f"{name}.py")
            if os.path.isfile(path):
                os.unlink(path)
            _reset_task(
                await _task_for_key(session, name),
                status=AuthoringTaskStatus.FAILED.value,
                category=AuthoringFailureCategory.VALIDATION_FAILED.value,
                error="pruned: script failed to import",
            )

    assignments = {
        a.extractor_key: a
        for a in (await session.execute(select(SourceExtractorAssignment))).scalars()
    }

    deployed: list[RegisteredExtractor] = []
    for entry in entries:
        key = entry.extractor.key
        module_short = entry.module_name.rsplit(".", 1)[-1]
        if module_short in _IGNORED_MODULES:
            continue
        urls = [t.url for t in entry.extractor.targets]
        if any(is_aggregator_url(url, settings=cfg) for url in urls):
            report.deleted_aggregator.append(key)
            await _delete_script(
                session,
                entry_key=key,
                module_name=entry.module_name,
                apply=apply,
                status=AuthoringTaskStatus.FAILED.value,
                category=AuthoringFailureCategory.AGGREGATOR.value,
                error="pruned: targets a directory/aggregator site",
            )
            continue
        if any(is_umbrella_url(url, settings=cfg) for url in urls):
            report.deleted_umbrella.append(key)
            await _delete_script(
                session,
                entry_key=key,
                module_name=entry.module_name,
                apply=apply,
                status=AuthoringTaskStatus.SKIPPED_REVIEW.value,
                category=AuthoringFailureCategory.UMBRELLA_REVIEW.value,
                error="pruned: targets a multi-mosque umbrella site — needs review",
            )
            continue
        assignment = assignments.get(key)
        if assignment is None or assignment.status != "active":
            report.deleted_orphan.append(key)
            await _delete_script(
                session,
                entry_key=key,
                module_name=entry.module_name,
                apply=apply,
                status=AuthoringTaskStatus.FAILED.value,
                category=AuthoringFailureCategory.VALIDATION_FAILED.value,
                error="pruned: no active assignment",
            )
            continue
        deployed.append(entry)

    if not run_smoke:
        report.kept.extend(entry.extractor.key for entry in deployed)
        return report

    from uk_jamaat_directory.ingest.authoring.smoke_test import smoke_test_extractor

    semaphore = asyncio.Semaphore(max(1, concurrency))

    # Resolve source URLs sequentially (one shared session), then smoke-test
    # concurrently (smoke tests are DB-free).
    source_urls: dict[str, str] = {}
    for entry in deployed:
        assignment = assignments[entry.extractor.key]
        source = await session.get(MosqueSource, assignment.source_id)
        source_urls[entry.extractor.key] = (source.source_url if source else "") or ""

    async def _smoke(entry: RegisteredExtractor) -> tuple[RegisteredExtractor, object]:
        async with semaphore:
            return entry, await smoke_test_extractor(
                extractor_key=entry.extractor.key,
                source_url=source_urls[entry.extractor.key],
                settings=cfg,
            )

    results = await asyncio.gather(*(_smoke(entry) for entry in deployed))
    for entry, smoke in results:
        key = entry.extractor.key
        if smoke.ok:
            report.kept.append(key)
            if apply:
                task = await _task_for_key(session, key)
                if task is not None:
                    task.metadata_ = {**(task.metadata_ or {}), "smoke": smoke.as_dict()}
        else:
            report.deleted_smoke_failed[key] = smoke.issues
            await _delete_script(
                session,
                entry_key=key,
                module_name=entry.module_name,
                apply=apply,
                status=AuthoringTaskStatus.FAILED.value,
                category=AuthoringFailureCategory.VALIDATION_FAILED.value,
                error="pruned: smoke test failed: " + "; ".join(smoke.issues)[:400],
            )
    return report
