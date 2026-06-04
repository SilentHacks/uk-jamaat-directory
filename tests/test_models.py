from __future__ import annotations

from uk_jamaat_directory import models
from uk_jamaat_directory.db.base import Base


def test_core_models_are_registered_with_metadata() -> None:
    expected_tables = {
        "mosques",
        "mosque_sources",
        "mosque_aliases",
        "mosque_attributes",
        "source_artifacts",
        "extraction_runs",
        "schedule_candidates",
        "schedule_occurrences",
        "source_health",
        "dataset_versions",
        "change_events",
        "moderation_actions",
        "mosque_claims",
        "corrections",
    }

    assert expected_tables.issubset(Base.metadata.tables)
    assert models.Mosque.__tablename__ == "mosques"
    assert models.ScheduleOccurrence.__tablename__ == "schedule_occurrences"
