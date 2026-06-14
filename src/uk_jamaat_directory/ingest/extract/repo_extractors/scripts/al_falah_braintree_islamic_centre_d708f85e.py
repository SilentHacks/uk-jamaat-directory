import json
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
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
    key = "al_falah_braintree_islamic_centre_d708f85e"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("braintreemosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="mawaqit-widget",
            url="https://mawaqit.net/en/m/alfalah-braintree?showNotification=0&showSearchButton=0&showFooter=0&showFlashMessage=0&view=mobile",
            kind=TargetKind.RENDERED_HTML,
            requires_javascript=True,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Extract jamaat times from Mawaqit JSON embedded in the HTML."""
        artifact = ctx.artifact("mawaqit-widget")
        if not artifact.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="mawaqit-widget artifact is empty",
                        target_label="mawaqit-widget",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )

        html_str = artifact.text()

        # Find iqamaCalendar in the HTML
        idx = html_str.find('"iqamaCalendar"')
        if idx < 0:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_iqama_data",
                        message="iqamaCalendar not found in artifact",
                        target_label="mawaqit-widget",
                    )
                ],
                no_schedule_reason="no iqama calendar data found",
            )

        # Find the opening bracket after the colon
        colon_idx = html_str.find(":", idx)
        bracket_idx = html_str.find("[", colon_idx)
        if bracket_idx < 0:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_iqama_data",
                        message="iqamaCalendar JSON structure not found",
                        target_label="mawaqit-widget",
                    )
                ],
                no_schedule_reason="no iqama calendar JSON structure found",
            )

        # Find matching closing bracket
        depth = 0
        end_idx = -1
        for i in range(bracket_idx, len(html_str)):
            if html_str[i] == "[":
                depth += 1
            elif html_str[i] == "]":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break

        if end_idx < 0:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_iqama_data",
                        message="could not find end of iqamaCalendar JSON",
                        target_label="mawaqit-widget",
                    )
                ],
                no_schedule_reason="iqama calendar JSON end not found",
            )

        iqama_json_str = html_str[bracket_idx:end_idx]
        try:
            iqama_calendar = json.loads(iqama_json_str)
        except json.JSONDecodeError:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="json_parse_error",
                        message="failed to parse iqamaCalendar JSON",
                        target_label="mawaqit-widget",
                    )
                ],
                no_schedule_reason="iqama calendar JSON malformed",
            )

        current_year = datetime.now().year
        rows = []
        warnings = []

        # iqama_calendar is a list of 12 months (0-indexed by month, 1-indexed by day)
        for month_idx, month_data in enumerate(iqama_calendar):
            month_num = month_idx + 1  # Convert to 1-12
            for day_str, times in month_data.items():
                day_num = int(day_str)
                try:
                    row_date = datetime(current_year, month_num, day_num).date()
                except ValueError:
                    # Invalid date (e.g., Feb 30)
                    continue

                # times is a list of 5 jamaat times: [Fajr, Dhuhr, Asr, Maghrib, Isha]
                if len(times) >= 5:
                    prayers = [
                        (Prayer.FAJR, times[0]),
                        (Prayer.DHUHR, times[1]),
                        (Prayer.ASR, times[2]),
                        (Prayer.MAGHRIB, times[3]),
                        (Prayer.ISHA, times[4]),
                    ]
                    for prayer, time_str in prayers:
                        try:
                            jamaat_time = coerce_time(time_str)
                            evidence = ctx.evidence(
                                target_label="mawaqit-widget",
                                extractor_key=self.key,
                                extractor_version=self.version,
                                raw_text=f"{row_date} {prayer.value} {time_str}",
                            )
                            rows.append(
                                ExtractorRow(
                                    date=row_date,
                                    prayer=prayer,
                                    jamaat_time=jamaat_time,
                                    timezone=ctx.timezone,
                                    evidence=evidence,
                                )
                            )
                        except Exception as e:
                            warnings.append(
                                ExtractorWarning(
                                    code="time_parse_error",
                                    message=f"failed to parse {prayer.value} time {time_str}: {str(e)}",
                                    target_label="mawaqit-widget",
                                )
                            )

        if not rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="no valid jamaat times extracted",
            )

        return ExtractorResult(rows=rows, warnings=warnings)
