from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.exports.types import ExportResult
from uk_jamaat_directory.tasks.exports import _generate_latest_exports_async


@pytest.mark.asyncio
async def test_generate_latest_exports_skips_when_disabled(test_settings) -> None:
    settings = Settings(**{**test_settings.model_dump(), "export_enabled": False})

    with patch("uk_jamaat_directory.tasks.exports.get_settings", return_value=settings):
        result = await _generate_latest_exports_async()

    assert result == {"skipped": True, "reason": "export disabled"}


@pytest.mark.asyncio
async def test_generate_latest_exports_raises_on_errors(test_settings) -> None:
    settings = Settings(**{**test_settings.model_dump(), "export_enabled": True})
    failed = ExportResult(version="", errors=["dataset version not found"])

    with (
        patch("uk_jamaat_directory.tasks.exports.get_settings", return_value=settings),
        patch(
            "uk_jamaat_directory.tasks.exports.generate_dataset_exports",
            new=AsyncMock(return_value=failed),
        ),
        patch("uk_jamaat_directory.tasks.exports.cli_db_session") as session_cm,
    ):
        session_cm.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        session_cm.return_value.__aexit__ = AsyncMock(return_value=None)

        with pytest.raises(RuntimeError, match="dataset version not found"):
            await _generate_latest_exports_async()


def test_generate_latest_exports_task_runs_async_helper() -> None:
    with patch(
        "uk_jamaat_directory.tasks.exports._generate_latest_exports_async",
        new=AsyncMock(return_value={"version": "2026-06-04.1"}),
    ) as async_mock:
        from uk_jamaat_directory.tasks.exports import generate_latest_exports_task

        result = generate_latest_exports_task()

    async_mock.assert_awaited_once()
    assert result == {"version": "2026-06-04.1"}
