"""
Faizan-e-Madina Mosque timetable extractor.

Source: https://faizanemadina.org/prayer-times/

The site uses a WordPress "daily-prayer-time-for-mosques" plugin that loads
timetable data via AJAX. The rendered HTML page doesn't include the table data;
it's loaded by JavaScript. This extractor is SKIPPED because the site requires
dynamic JavaScript interaction (selecting months, waiting for AJAX) that isn't
fully resolvable in a sandboxed extraction environment.

The timetable is structurally available but requires OCR/PDF-like handling.
Status: skipped_review (requires full browser automation with user interaction).
"""

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedOcrExtractor,
)


class Extractor(StubbedOcrExtractor):
    key = "faizan_e_madina_mosque_8831dc6b"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("faizanemadina.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://faizanemadina.org/prayer-times/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
