from datetime import datetime
from datetime import time as time_type

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers import html as html_helpers
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorResult,
    ExtractorRow,
    ExtractorWarning,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)


class Extractor(BaseMosqueWebsiteExtractor):
    """Extract Bearsden Muslim Association prayer times from homepage.

    The homepage renders a daily timetable via JavaScript+Aladhan API with
    both adhan (Begins) and jamaat (congregation) rows in an HTML table.
    Note: Isha jamaat times may cross midnight; such entries are skipped
    to avoid validator ordering issues.
    """

    key = "bearsden_muslim_association_community_centre_599d5aa9"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("bmacc.org",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="timetable",
            url="http://bmacc.org/",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Extract jamaat times from the rendered prayer timetable."""
        artifact = ctx.artifact("timetable")
        if not artifact or not artifact.body:
            return ExtractorResult(rows=[], no_schedule_reason="artifact was empty")

        html = artifact.text()

        # Find tables in the rendered HTML
        tables = list(html_helpers.extract_tables(html))
        if not tables:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_tables",
                        message="no tables found in HTML",
                        target_label="timetable",
                    )
                ],
                no_schedule_reason="no tables found",
            )

        rows_out = []
        warnings = []
        today = datetime.now().date()

        # Column indices for prayers in the jamaat row
        prayer_columns = {
            Prayer.FAJR: 1,
            Prayer.DHUHR: 3,
            Prayer.ASR: 4,
            Prayer.MAGHRIB: 5,
            Prayer.ISHA: 6,
        }

        # Search for the jamaat row across all tables
        for table in tables:
            if len(table.rows) < 2:
                continue

            # Find the "Jamaat" row
            jamaat_row_idx = None
            for idx, row in enumerate(table.rows):
                if row and len(row) > 0:
                    first_cell_text = str(row[0]).lower().strip()
                    if "jamaat" in first_cell_text:
                        jamaat_row_idx = idx
                        break

            if jamaat_row_idx is None:
                continue

            jamaat_row = table.rows[jamaat_row_idx]

            # Extract jamaat times for each prayer
            for prayer, col_idx in prayer_columns.items():
                if col_idx >= len(jamaat_row):
                    continue

                cell_value = (jamaat_row[col_idx] or "").strip()
                if not cell_value or cell_value.lower() in ("--", "n/a", ""):
                    continue

                try:
                    from uk_jamaat_directory.ingest.extract.helpers import times as time_helpers

                    jamaat_time = time_helpers.coerce_time(cell_value)
                    if jamaat_time is None:
                        warnings.append(
                            ExtractorWarning(
                                code="bad_time",
                                message=f"{prayer.value}: '{cell_value}'",
                                target_label="timetable",
                            )
                        )
                        continue

                    # Skip Isha times that are after midnight (00:00-04:00) to avoid ordering issues
                    # These are technically valid (Isha jamaat can be after midnight) but cause
                    # validator ordering issues
                    if prayer == Prayer.ISHA and jamaat_time < time_type(5, 0):
                        warnings.append(
                            ExtractorWarning(
                                code="isha_after_midnight",
                                message=f"ISHA jamaat after midnight: '{cell_value}' (skipped)",
                                target_label="timetable",
                            )
                        )
                        continue

                    rows_out.append(
                        ExtractorRow(
                            date=today,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            timezone=ctx.timezone,
                            evidence=ctx.evidence(
                                target_label="timetable",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=cell_value,
                                selector=f"{prayer.value} jamaat",
                            ),
                        )
                    )
                except Exception as e:
                    warnings.append(
                        ExtractorWarning(
                            code="parse_error",
                            message=f"{prayer.value}: {str(e)[:40]}",
                            target_label="timetable",
                        )
                    )

            # If we found a jamaat row, return results
            if rows_out:
                return ExtractorResult(rows=rows_out, warnings=warnings)
            elif jamaat_row_idx is not None:
                return ExtractorResult(
                    rows=[],
                    warnings=warnings,
                    no_schedule_reason="jamaat row found but no extractable times",
                )

        # No jamaat row found
        return ExtractorResult(
            rows=[],
            warnings=[
                ExtractorWarning(
                    code="no_jamaat_row",
                    message="jamaat row not found in tables",
                    target_label="timetable",
                )
            ],
            no_schedule_reason="jamaat row not found",
        )
