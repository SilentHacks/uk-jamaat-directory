"""Glasgow Central Mosque prayer times extractor."""

import json
from datetime import date as date_type
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
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
    key = "glasgow_central_mosque_72e65ee9"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("centralmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="api_month",
            url="https://centralmosque.co.uk/?rest_route=/dpt/v1/prayertime&filter=month&month=6&year=2026",
            kind=TargetKind.JSON,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        artifact = ctx.artifact("api_month")
        if not artifact.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="API response is empty",
                        target_label="api_month",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )

        try:
            data = json.loads(artifact.text())
        except json.JSONDecodeError as e:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="invalid_json",
                        message=f"API response is not valid JSON: {e}",
                        target_label="api_month",
                    )
                ],
                no_schedule_reason="invalid JSON response",
            )

        if not isinstance(data, list) or len(data) == 0:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="unexpected_format",
                        message="API response is not a list or is empty",
                        target_label="api_month",
                    )
                ],
                no_schedule_reason="unexpected API format",
            )

        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        month_data = data[0]

        if not isinstance(month_data, list):
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="unexpected_format",
                        message="API month data is not a list",
                        target_label="api_month",
                    )
                ],
                no_schedule_reason="unexpected data structure",
            )

        for idx, entry in enumerate(month_data):
            if not isinstance(entry, dict):
                continue

            date_str = entry.get("d_date")
            if not date_str:
                continue

            try:
                prayer_date = date_type.fromisoformat(date_str)
            except ValueError:
                warnings.append(
                    ExtractorWarning(
                        code="bad_date",
                        message=f"entry {idx} has invalid date '{date_str}'",
                        target_label="api_month",
                    )
                )
                continue

            # Extract jamaat times for daily prayers
            for prayer, jam_key in [
                (Prayer.FAJR, "fajr_jamah"),
                (Prayer.DHUHR, "zuhr_jamah"),
                (Prayer.ASR, "asr_jamah"),
                (Prayer.MAGHRIB, "maghrib_jamah"),
                (Prayer.ISHA, "isha_jamah"),
            ]:
                jamaat_str = entry.get(jam_key, "").strip()
                if not jamaat_str or jamaat_str == "00:00:00":
                    continue

                try:
                    jamaat_time = datetime.strptime(jamaat_str, "%H:%M:%S").time()
                    evidence = ctx.evidence(
                        target_label="api_month",
                        extractor_key=self.key,
                        extractor_version=self.version,
                        raw_text=f"{date_str} {prayer.value} {jamaat_str}",
                        selector=f"entry[{idx}].{jam_key}",
                    )
                    extracted_rows.append(
                        ExtractorRow(
                            date=prayer_date,
                            prayer=prayer,
                            jamaat_time=jamaat_time,
                            timezone=ctx.timezone,
                            evidence=evidence,
                        )
                    )
                except (ValueError, AttributeError):
                    warnings.append(
                        ExtractorWarning(
                            code="bad_jamaat",
                            message=f"entry {idx} {prayer.value} has invalid time '{jamaat_str}'",
                            target_label="api_month",
                        )
                    )
                    continue

        if not extracted_rows:
            return ExtractorResult(
                rows=[],
                warnings=warnings
                or [
                    ExtractorWarning(
                        code="no_extractable_rows",
                        message="no jamaat times found in API response",
                        target_label="api_month",
                    )
                ],
                no_schedule_reason="no jamaat times in response",
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
