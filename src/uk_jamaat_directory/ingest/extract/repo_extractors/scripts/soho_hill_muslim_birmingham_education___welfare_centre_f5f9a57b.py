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
    """Site embeds Islamic Finder widget (aggregator, not allowed).

    Soho Hill Muslim Birmingham embeds prayer times via Islamic Finder widget
    (islamicfinder.org), an aggregator domain explicitly not allowed. Islamic Finder
    publishes calculated times, not mosque-confirmed jamaat times. No local jamaat
    timetable exists on the mosque's own domain. Manual review needed.
    """

    key = "soho_hill_muslim_birmingham_education___welfare_centre_f5f9a57b"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("sohohillmuslim.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer times",
            url="https://sohohillmuslim.org.uk/",
            kind=TargetKind.IMAGE,
            requires_ocr=True,
        ),
    )
