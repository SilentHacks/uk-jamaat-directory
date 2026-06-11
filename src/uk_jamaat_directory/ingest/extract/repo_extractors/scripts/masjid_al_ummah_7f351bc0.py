import re
from datetime import datetime
from uk_jamaat_directory.domain import Prayer
from uk_jamaat_directory.ingest.extract.helpers.times import coerce_time
from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    RefreshPolicy, RunFrequency, SourceMatch, TargetKind, TargetSpec, ExtractorResult, ExtractorRow, ExtractorEvidence,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.declarative import (
    BaseMosqueWebsiteExtractor,
)


class Extractor(BaseMosqueWebsiteExtractor):
    key = "masjid_al_ummah_7f351bc0"
    version = "2026.06.11.1"
    source_match = SourceMatch(domains=("abrahamicfoundation.org.uk",))
    refresh_policy = RefreshPolicy(frequency=RunFrequency.MONTHLY)
    targets = (
        TargetSpec(
            label="timetable",
            url="https://legacy.abrahamicfoundation.org.uk/wp-content/uploads/2020/08/05-May-Salah-Timetable-Masjid-al-Ummah-1.pdf",
            kind=TargetKind.PDF,
        ),
    )

    def extract(self, ctx):
        from uk_jamaat_directory.ingest.extract.helpers.pdf import extract_text

        artifact = ctx.artifact("timetable")
        text = extract_text(artifact.body)

        if not text:
            return ExtractorResult(rows=[], no_schedule_reason="could not extract text from PDF")

        lines = text.split('\n')

        # Find the month/year from the text
        month_year_pattern = r'(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(\d{4})'
        month_match = None
        for line in lines:
            match = re.search(month_year_pattern, line)
            if match:
                month_match = match
                break

        if not month_match:
            return ExtractorResult(rows=[], no_schedule_reason="could not find month/year in PDF")

        month_str = month_match.group(1)
        year = int(month_match.group(2))
        month_map = {
            'JANUARY': 1, 'FEBRUARY': 2, 'MARCH': 3, 'APRIL': 4, 'MAY': 5,
            'JUNE': 6, 'JULY': 7, 'AUGUST': 8, 'SEPTEMBER': 9,
            'OCTOBER': 10, 'NOVEMBER': 11, 'DECEMBER': 12
        }
        month = month_map.get(month_str, 5)

        rows = []
        day_pattern = r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thur|Thu|Fri|Sat|Sun)\s+(\d+)'

        # Track carry-forward values
        previous_times = {
            'fajr_iqamah': None,
            'dhuhr_time': None,
            'asr_iqamah': None,
            'isha_iqamah': None,
        }

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Check if this is a day/date line
            day_match = re.match(day_pattern, line)
            if day_match:
                date_num = int(day_match.group(2))

                try:
                    date = datetime(year, month, date_num).date()
                except ValueError:
                    i += 1
                    continue

                # Collect values until next day or end
                times_collected = []
                j = i + 1
                while j < len(lines):
                    val = lines[j].strip()
                    if not val:
                        j += 1
                        continue

                    # Stop if we hit another day line
                    if re.match(day_pattern, val):
                        break

                    times_collected.append(val)
                    j += 1

                # Process values with carry-forward handling
                # Expected sequence: IslamicDate, FajrTime, FajrIqamah, Sunrise,
                # DhuhrIqamah, DhuhrTime, AsrTime, AsrIqamah, MaghribTime, IshaTime, IshaIqamah

                if len(times_collected) >= 11:
                    try:
                        # Map indices to values, handling carry-forward markers
                        values_map = {}
                        idx = 0
                        expected_keys = [
                            'islamic_date', 'fajr_time', 'fajr_iqamah', 'sunrise',
                            'dhuhr_iqamah', 'dhuhr_time', 'asr_time', 'asr_iqamah',
                            'maghrib_time', 'isha_time', 'isha_iqamah'
                        ]

                        for expected_key in expected_keys:
                            if idx < len(times_collected):
                                val = times_collected[idx]
                                # Check for carry-forward marker
                                if val in ['"', '""', '"  "']:
                                    # Use previous value
                                    if expected_key == 'fajr_iqamah':
                                        values_map[expected_key] = previous_times['fajr_iqamah']
                                    elif expected_key == 'dhuhr_time':
                                        values_map[expected_key] = previous_times['dhuhr_time']
                                    elif expected_key == 'asr_iqamah':
                                        values_map[expected_key] = previous_times['asr_iqamah']
                                    elif expected_key == 'isha_iqamah':
                                        values_map[expected_key] = previous_times['isha_iqamah']
                                    else:
                                        values_map[expected_key] = None
                                else:
                                    values_map[expected_key] = val
                                idx += 1

                        evidence = ExtractorEvidence(
                            target_label=artifact.target_label,
                            target_url=artifact.target_url,
                            extractor_key=self.key,
                            extractor_version=self.version,
                        )

                        # Extract and convert times
                        fajr_iqamah = coerce_time(values_map.get('fajr_iqamah'), prayer=Prayer.FAJR)
                        dhuhr_iqamah = coerce_time(values_map.get('dhuhr_iqamah'), prayer=Prayer.DHUHR)
                        asr_iqamah = coerce_time(values_map.get('asr_iqamah'), prayer=Prayer.ASR)
                        maghrib_time = coerce_time(values_map.get('maghrib_time'), prayer=Prayer.MAGHRIB)
                        isha_iqamah = coerce_time(values_map.get('isha_iqamah'), prayer=Prayer.ISHA)

                        # Update previous values for next iteration
                        if fajr_iqamah:
                            previous_times['fajr_iqamah'] = values_map.get('fajr_iqamah')
                        if values_map.get('dhuhr_time') and values_map.get('dhuhr_time') not in ['"', '""', '"  "']:
                            previous_times['dhuhr_time'] = values_map.get('dhuhr_time')
                        if asr_iqamah:
                            previous_times['asr_iqamah'] = values_map.get('asr_iqamah')
                        if isha_iqamah:
                            previous_times['isha_iqamah'] = values_map.get('isha_iqamah')

                        # Create rows for each prayer that has a time
                        if fajr_iqamah:
                            rows.append(ExtractorRow(
                                date=date,
                                prayer=Prayer.FAJR,
                                jamaat_time=fajr_iqamah,
                                evidence=evidence,
                            ))
                        if dhuhr_iqamah:
                            rows.append(ExtractorRow(
                                date=date,
                                prayer=Prayer.DHUHR,
                                jamaat_time=dhuhr_iqamah,
                                evidence=evidence,
                            ))
                        if asr_iqamah:
                            rows.append(ExtractorRow(
                                date=date,
                                prayer=Prayer.ASR,
                                jamaat_time=asr_iqamah,
                                evidence=evidence,
                            ))
                        if maghrib_time:
                            rows.append(ExtractorRow(
                                date=date,
                                prayer=Prayer.MAGHRIB,
                                jamaat_time=maghrib_time,
                                evidence=evidence,
                            ))
                        if isha_iqamah:
                            rows.append(ExtractorRow(
                                date=date,
                                prayer=Prayer.ISHA,
                                jamaat_time=isha_iqamah,
                                evidence=evidence,
                            ))
                    except (ValueError, TypeError, IndexError):
                        pass

                i = j if j > i + 1 else i + 1
            else:
                i += 1

        if not rows:
            return ExtractorResult(rows=[], no_schedule_reason="no prayer times found in PDF")

        return ExtractorResult(rows=rows)
