import json
import re
from datetime import datetime

from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorEvidence,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
    TargetKind,
    TargetSpec,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "bristol_central_mosque_01e0c34b"
    version = "2026.06.16.1"
    source_match = SourceMatch(domains=("bristolcentralmosque.co.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="prayer_times",
            url="http://bristolcentralmosque.co.uk/prayer",
            kind=TargetKind.RENDERED_HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        rows = []

        # Get the artifact (artifacts is a dict)
        if not ctx.artifacts:
            return ExtractorResult(rows=[], no_schedule_reason="No artifacts provided")

        artifact = next(iter(ctx.artifacts.values()))
        html = artifact.text() if callable(artifact.text) else artifact.text

        # Extract prayerTimesData JavaScript object from the page
        match = re.search(r"const\s+prayerTimesData\s*=\s*(\{.*?\});", html, re.DOTALL)
        if not match:
            return ExtractorResult(
                rows=[], no_schedule_reason="Prayer times data not found in page"
            )

        js_obj = match.group(1)

        # Remove comments
        js_obj = re.sub(r"//.*?$", "", js_obj, flags=re.MULTILINE)

        # Convert JavaScript object to valid JSON by adding quotes around keys
        # Replace unquoted keys with quoted keys: match { or , followed by word:
        json_str = re.sub(r"([{,]\s*)(\w+):", r'\1"\2":', js_obj)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return ExtractorResult(
                rows=[], no_schedule_reason=f"Failed to parse prayer times data: {str(e)[:50]}"
            )

        for date_str, prayer_data in data.items():
            try:
                row_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            # Map jamaat times, with prayer name for am/pm inference.
            # Prefer explicitly named jamaat fields; for Maghrib fall back to
            # "maghrib" if no separate "maghribJamaat" field exists in the data
            # (some mosque JS data omits it because Maghrib is prayed at adhan time).
            time_mappings = {
                Prayer.FAJR: (["fajarJamaat"], "fajr"),
                Prayer.DHUHR: (["zuhurJamaat"], "dhuhr"),
                Prayer.ASR: (["asrJamaat"], "asr"),
                Prayer.MAGHRIB: (["maghribJamaat", "maghrib"], "maghrib"),
                Prayer.ISHA: (["ishaJamaat"], "isha"),
            }

            for prayer, (field_names, prayer_name) in time_mappings.items():
                time_str = None
                field_used = None
                for fn in field_names:
                    if fn in prayer_data:
                        time_str = prayer_data[fn]
                        field_used = fn
                        break
                if time_str is None:
                    continue
                try:
                    prayer_time = coerce_time(time_str, prayer=prayer_name)
                    if prayer_time:
                        evidence = ExtractorEvidence(
                            target_label=self.targets[0].label,
                            target_url=self.targets[0].url,
                            extractor_key=self.key,
                            extractor_version=self.version,
                            derivation={
                                "field": field_used,
                                "source": "embedded_javascript_data",
                            },
                        )
                        row = ExtractorRow(
                            date=row_date,
                            prayer=prayer,
                            jamaat_time=prayer_time,
                            evidence=evidence,
                        )
                        rows.append(row)
                except Exception:
                    pass

        if not rows:
            return ExtractorResult(
                rows=[], no_schedule_reason="No prayer times extracted from data"
            )

        return ExtractorResult(rows=rows, warnings=[])
