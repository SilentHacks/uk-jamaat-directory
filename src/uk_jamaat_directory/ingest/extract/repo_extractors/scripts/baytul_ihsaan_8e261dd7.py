from datetime import date

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorEvidence,
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    TableTimetableExtractor,
)


class Extractor(TableTimetableExtractor):
    key = "baytul_ihsaan_8e261dd7"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("dfhtrust.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://dfhtrust.org/locations/baytul-ihsaan",
            kind=TargetKind.HTML,
        ),
    )
    table_keywords = ("salah", "jamat")
    date_column = 0
    prayer_columns = {
        Prayer.FAJR: 2,
        Prayer.DHUHR: 2,
        Prayer.ASR: 2,
        Prayer.MAGHRIB: 2,
        Prayer.ISHA: 2,
    }

    def _extract_from_table(self, ctx: ExtractContext, table):
        # Map prayer names to Prayers and extract jamaat times (column 2)
        prayer_map = {
            "Fajr": Prayer.FAJR,
            "Zuhr": Prayer.DHUHR,
            "Asr": Prayer.ASR,
            "Magrib": Prayer.MAGHRIB,
            "Isha": Prayer.ISHA,
        }

        rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        today = date.today()

        for row in table.body():
            cleaned_row = [self.clean_cell(cell) for cell in row]
            if not cleaned_row or len(cleaned_row) < 3:
                continue

            prayer_name = cleaned_row[0]
            if prayer_name not in prayer_map:
                continue

            jamaat_time = cleaned_row[2]
            if not jamaat_time:
                continue

            prayer = prayer_map[prayer_name]
            jamaat = coerce_time(jamaat_time)
            if not jamaat:
                continue

            evidence = ExtractorEvidence(
                target_label=self.targets[0].label,
                target_url=self.targets[0].url,
                extractor_key=self.key,
                extractor_version=self.version,
            )

            rows.append(
                ExtractorRow(
                    prayer=prayer,
                    date=today,
                    jamaat_time=jamaat,
                    evidence=evidence,
                )
            )

        return ExtractorResult(rows=rows, warnings=warnings)
