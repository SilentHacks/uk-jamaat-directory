"""Deterministic extractor for Shah Jalal Mosque Southampton prayer times."""

import json
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
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


class Extractor(BaseMosqueWebsiteExtractor):
    """Extractor for Shah Jalal Mosque Southampton via JSON API."""

    key = "shah_jalal_mosque_and_islamic_centre_07f1ccc6"
    version = "2026.06.13.1"
    source_match = SourceMatch(domains=("smicsouthampton.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer_times_api",
            url="https://smicsouthampton.co.uk/api/prayers",
            kind=TargetKind.JSON,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Parse JSON API and extract jamaat prayer times."""
        artifact = ctx.artifact("prayer_times_api")
        if not artifact or not artifact.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="prayer_times_api artifact is empty",
                        target_label="prayer_times_api",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )

        try:
            text = artifact.text()
            data = json.loads(text)
        except json.JSONDecodeError as e:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="json_parse_error",
                        message=f"Failed to parse JSON: {e}",
                        target_label="prayer_times_api",
                    )
                ],
                no_schedule_reason="JSON parsing failed",
            )

        if not isinstance(data, dict) or "model" not in data:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="invalid_api_response",
                        message="Invalid API response structure",
                        target_label="prayer_times_api",
                    )
                ],
                no_schedule_reason="invalid API response",
            )

        model = data.get("model", {})
        if not isinstance(model, dict):
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="invalid_model",
                        message="model field is not a dict",
                        target_label="prayer_times_api",
                    )
                ],
                no_schedule_reason="model field invalid",
            )

        salah_timings = model.get("salahTimings", [])
        if not isinstance(salah_timings, list) or not salah_timings:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="no_salah_timings",
                        message="No salahTimings found",
                        target_label="prayer_times_api",
                    )
                ],
                no_schedule_reason="no prayer times available",
            )

        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []
        current_year = datetime.now().year

        # Parse daily prayer timings
        for day_data in salah_timings:
            day_num = day_data.get("day")
            month_num = day_data.get("month")

            if day_num is None or month_num is None:
                continue

            try:
                date_obj = datetime(current_year, month_num, day_num).date()
            except ValueError:
                warnings.append(
                    ExtractorWarning(
                        code="invalid_date",
                        message=f"Invalid date: {current_year}-{month_num:02d}-{day_num:02d}",
                        target_label="prayer_times_api",
                    )
                )
                continue

            for prayer_key, prayer_enum in [
                ("fajr", Prayer.FAJR),
                ("zuhr", Prayer.DHUHR),
                ("asr", Prayer.ASR),
                ("maghrib", Prayer.MAGHRIB),
                ("isha", Prayer.ISHA),
            ]:
                prayer_list = day_data.get(prayer_key, [])
                if not prayer_list or not isinstance(prayer_list, list):
                    continue

                prayer_entry = prayer_list[0]
                jamaat_time_str = prayer_entry.get("iqamahTime")

                if not jamaat_time_str:
                    continue

                jamaat_time = coerce_time(jamaat_time_str)
                if not jamaat_time:
                    warnings.append(
                        ExtractorWarning(
                            code="invalid_time",
                            message=f"Could not parse jamaat time '{jamaat_time_str}'",
                            target_label="prayer_times_api",
                        )
                    )
                    continue

                extracted_rows.append(
                    ExtractorRow(
                        prayer=prayer_enum,
                        date=date_obj,
                        jamaat_time=jamaat_time,
                        evidence=ExtractorEvidence(
                            target_label="prayer_times_api",
                            target_url=self.targets[0].url,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            derivation={"field": f"{prayer_key}/iqamahTime"},
                        ),
                    )
                )

        # Parse Jumu'ah timings - find all Fridays and add primary jumu'ah only
        fridays = []
        for day_data in salah_timings:
            day_num = day_data.get("day")
            month_num = day_data.get("month")
            if day_num is not None and month_num is not None:
                try:
                    date_obj = datetime(current_year, month_num, day_num).date()
                    if date_obj.weekday() == 4:  # Friday
                        fridays.append(date_obj)
                except ValueError:
                    pass

        jumah_timings = model.get("jumahSalahIqamahTimings", [])
        if isinstance(jumah_timings, list) and jumah_timings:
            # Use only the primary jumu'ah time
            primary_jumah = next((j for j in jumah_timings if j.get("isPrimary")), jumah_timings[0])
            jamaat_time_str = primary_jumah.get("iqamahTime")
            if jamaat_time_str:
                jamaat_time = coerce_time(jamaat_time_str)
                if jamaat_time:
                    for friday_date in fridays:
                        extracted_rows.append(
                            ExtractorRow(
                                prayer=Prayer.JUMUAH,
                                date=friday_date,
                                jamaat_time=jamaat_time,
                                evidence=ExtractorEvidence(
                                    target_label="prayer_times_api",
                                    target_url=self.targets[0].url,
                                    extractor_key=self.key,
                                    extractor_version=self.version,
                                    derivation={
                                        "field": "jumahSalahIqamahTimings/iqamahTime",
                                        "isPrimary": True,
                                    },
                                ),
                            )
                        )
                else:
                    warnings.append(
                        ExtractorWarning(
                            code="invalid_jumah_time",
                            message="Could not parse primary jumu'ah jamaat time",
                            target_label="prayer_times_api",
                        )
                    )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
