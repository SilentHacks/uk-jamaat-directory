from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy, RunFrequency, SourceMatch, TargetKind, TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    StubbedOcrExtractor,
)


class Extractor(StubbedOcrExtractor):
    key = "banbury_sheikh_bin_baaz_masjid_eaaa8669"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("jamiatbanbury.co.uk", "mawaqit.net"))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="mawaqit_widget",
            url="https://mawaqit.net/en/w/banbury-sheikh-bin-baaz-mosque-banbury-oxfordshire-ox16-0dh-united-kingdom?showOnly5PrayerTimes=0",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )
    no_schedule_reason = "awaiting OCR"
