# Public API Contracts

Generated contract artifacts for the UK Jamaat Directory public read API (Phase 4).

Regenerate after changing routes or public response models in `src/uk_jamaat_directory/schemas/public.py`:

```bash
make export-contracts
```

## Files

| File | Description |
|------|-------------|
| `openapi.json` | Full FastAPI OpenAPI 3 document (all `/v1` routes) |
| `MosqueListResponse.json` | Paginated mosque list |
| `MosqueDetailPublic.json` | Mosque detail with public sources |
| `TimesResponse.json` | Mosque timetable for a date range |
| `NearbyTimesResponse.json` | Nearby published occurrences |
| `ChangeFeedResponse.json` | Append-only change feed page |
| `SnapshotResponse.json` | Dataset snapshot metadata |

Interactive docs when running the API locally: http://localhost:8000/docs

## Publication filtering

JSON Schemas describe public response shapes only. Timetable endpoints omit data tied to sources that are not `public_redistribution_allowed`. See [CONTEXT.md](../../CONTEXT.md) and ADR 0003.
