# Public API Contracts

Generated contract artifacts for the UK Jamaat Directory public read API.

Regenerate after changing routes or public response models in `src/uk_jamaat_directory/schemas/public.py`:

```bash
make export-contracts
```

## Files

| File | Description |
|------|-------------|
| `openapi.json` | Public OpenAPI 3 document (public `/v1` routes only; admin excluded) |
| `MosqueListResponse.json` | Paginated mosque list |
| `MosqueDetailPublic.json` | Mosque detail with public sources |
| `TimesResponse.json` | Mosque timetable for a date range |
| `NearbyTimesResponse.json` | Nearby published occurrences |
| `ChangeFeedResponse.json` | Append-only change feed page |
| `SnapshotResponse.json` | Dataset snapshot metadata |

The same filtered spec is served live at `/v1/openapi.json`, and rendered as an
interactive reference at `/docs/` (Scalar). The full spec including admin routes is
available only in non-production environments at `/internal/docs`.

## Publication filtering

JSON Schemas describe public response shapes only. Timetable endpoints omit data tied to sources that are not `public_redistribution_allowed`. See [CONTEXT.md](../../CONTEXT.md) and ADR 0003.

Admin routes (`/v1/admin/*`, OpenAPI tag `admin`) are intentionally excluded from the
public spec and the committed artifact. See ADR 0019.

## Versioning policy

- `/v1` is the stable public contract. Changes within `/v1` are **additive only** (new
  endpoints, new optional fields). Consumers must ignore unknown fields.
- A backwards-incompatible change introduces a new prefix (`/v2`) and runs in parallel
  with `/v1` for at least 90 days before `/v1` is retired.
- Dataset schema evolution is carried by `schema_version` in snapshot metadata, separate
  from the API version.

## Rate limits

- **Public read/contribution API:** 120 requests per minute per IP (`PUBLIC_RATE_LIMIT`).
  Exceeding it returns `429` with a `Retry-After` header. Health checks are exempt.
- **Community submissions** (mosque/correction/schedule/claim POSTs): 10 per minute per
  IP, a stricter inner gate.
- Sync from bulk snapshots and the `/v1/changes` feed instead of polling; do not call the
  API on your own request path (see ADR 0001).
