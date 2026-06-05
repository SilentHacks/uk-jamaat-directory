# Standard Mosque Feed v1

Mosques can publish machine-readable jamaat times at:

```text
/.well-known/uk-jamaat-directory.json
```

## Minimum schema

```json
{
  "schema_version": "1.0",
  "mosque_name": "Example Masjid",
  "timezone": "Europe/London",
  "updated_at": "2026-06-04T12:00:00Z",
  "valid_from": "2026-06-01",
  "valid_to": "2026-06-30",
  "times": [
    {
      "date": "2026-06-05",
      "prayer": "fajr",
      "start_time": "02:48",
      "jamaat_time": "03:45",
      "session_number": 1
    }
  ]
}
```

## Field notes

- `prayer`: `fajr`, `dhuhr`, `asr`, `maghrib`, `isha`, or `jumuah` (aliases such as `zuhr` and `jummah` are normalized on import).
- `jamaat_time`: required `HH:MM` in the feed timezone.
- `start_time`: optional adhan/prayer start time.
- `session_number`: defaults to `1`; use `2+` for multiple Jumuah sessions.
- `session_label`: optional human label (for example hall name).

The Directory fetches this feed when a mosque has a `website_url` and no recent MyLocalMasjid timetable source. Extracted rows become private `schedule_candidates` pending admin review and publication policy confirmation.

Synthetic examples live in [`data/fixtures/crawl/`](../../data/fixtures/crawl/).
