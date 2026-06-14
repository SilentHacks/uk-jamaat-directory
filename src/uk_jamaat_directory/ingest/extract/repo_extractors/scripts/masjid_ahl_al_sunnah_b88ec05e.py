from datetime import datetime
import re

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
    key = "masjid_ahl_al_sunnah_b88ec05e"
    version = "2026.06.13.1"

    source_match = SourceMatch(domains=("mamissionuk.com",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
    targets = (
        TargetSpec(
            label="masjidbox prayer times widget",
            url="https://mamissionuk.com/prayer",
            kind=TargetKind.RENDERED_HTML,
        ),
    )

    def extract(self, ctx: ExtractContext) -> ExtractorResult:
        """Extract jamaat times from masjidbox widget on the prayer page."""
        artifact = ctx.artifact("masjidbox prayer times widget")
        if not artifact.body:
            return ExtractorResult(
                rows=[],
                warnings=[
                    ExtractorWarning(
                        code="empty_artifact",
                        message="widget artifact is empty",
                        target_label="masjidbox prayer times widget",
                    )
                ],
                no_schedule_reason="artifact was empty",
            )

        html = artifact.text()
        extracted_rows: list[ExtractorRow] = []
        warnings: list[ExtractorWarning] = []

        # Parse jamaat times from masjidbox rendered output.
        # Pattern: "Fajr 1:53 AM ... Iqamah 4:00 AM"
        prayer_patterns = [
            (Prayer.FAJR, r"Fajr\s+(\d{1,2}:\d{2}\s*[AP]M).*?[Ii]qamah\s+(\d{1,2}:\d{2}\s*[AP]M)"),
            (Prayer.DHUHR, r"Dhuhr\s+(\d{1,2}:\d{2}\s*[AP]M).*?[Ii]qamah\s+(\d{1,2}:\d{2}\s*[AP]M)"),
            (Prayer.ASR, r"Asr\s+(\d{1,2}:\d{2}\s*[AP]M).*?[Ii]qamah\s+(\d{1,2}:\d{2}\s*[AP]M)"),
            (Prayer.MAGHRIB, r"Maghrib\s+(\d{1,2}:\d{2}\s*[AP]M).*?[Ii]qamah\s+(\d{1,2}:\d{2}\s*[AP]M)"),
            (Prayer.ISHA, r"Isha\s+(\d{1,2}:\d{2}\s*[AP]M).*?[Ii]qamah\s+(\d{1,2}:\d{2}\s*[AP]M)"),
            (Prayer.JUMUAH, r"Jumuah\s+(\d{1,2}:\d{2}\s*[AP]M).*?[Ii]qamah\s+(\d{1,2}:\d{2}\s*[AP]M)"),
        ]

        today = datetime.now().date()

        for prayer, pattern in prayer_patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                adhan_str = match.group(1).strip()
                iqamah_str = match.group(2).strip()

                jamaat_time = coerce_time(iqamah_str)
                if not jamaat_time:
                    warnings.append(
                        ExtractorWarning(
                            code="bad_time",
                            message=f"could not parse jamaat time '{iqamah_str}' for {prayer.value}",
                            target_label="masjidbox prayer times widget",
                        )
                    )
                    continue

                session_number = 1
                session_label = None
                if prayer == Prayer.JUMUAH:
                    sessions_today = [r for r in extracted_rows if r.date == today and r.prayer == Prayer.JUMUAH]
                    session_number = len(sessions_today) + 1
                    session_label = f"session {session_number}"

                evidence = ctx.evidence(
                    target_label="masjidbox prayer times widget",
                    extractor_key=self.key,
                    extractor_version=self.version,
                    raw_text=f"{prayer.value.title()} {adhan_str} / Iqamah {iqamah_str}",
                    selector=f"prayer-widget [{prayer.value}]",
                )

                extracted_rows.append(
                    ExtractorRow(
                        date=today,
                        prayer=prayer,
                        jamaat_time=jamaat_time,
                        timezone=ctx.timezone,
                        session_number=session_number,
                        session_label=session_label,
                        evidence=evidence,
                    )
                )

        if not extracted_rows:
            warnings.append(
                ExtractorWarning(
                    code="no_jamaat_times",
                    message="no jamaat times found in rendered widget",
                    target_label="masjidbox prayer times widget",
                )
            )
            return ExtractorResult(
                rows=[],
                warnings=warnings,
                no_schedule_reason="awaiting OCR",
            )

        return ExtractorResult(rows=extracted_rows, warnings=warnings)
