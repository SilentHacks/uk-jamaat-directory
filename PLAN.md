# Public UK Jamaat Directory + Private Sirat API Link Plan

## Summary

Split the system into two independent products:

- **UK Jamaat Directory**: a public data utility containing UK mosque identities, source provenance, prayer/jamaat timetable occurrences, freshness status, public API, and bulk exports.
- **Sirat API**: the private proprietary journey-planning backend. It consumes the public directory through a versioned read contract and keeps a local synced copy for route planning.

The directory owns mosque and jamaat data. Sirat owns journeys, routing, user/product behavior, rate limits, metrics, and proprietary planner logic. Sirat must not contain crawler/extraction/moderation infrastructure except a narrow sync adapter.

Best architecture: **public data service first, Sirat as one consumer among many**.

## Product Boundaries

### UK Jamaat Directory

Purpose:

- Maintain the canonical public UK mosque and jamaat timetable registry.
- Serve normalized public data through API and bulk snapshots.
- Track evidence, provenance, freshness, confidence, and mosque/community verification.
- Provide mosque claim and correction workflows.
- Publish enough data that other Muslim apps, community tools, and researchers can benefit.

Does not own:

- Journey planning.
- Routing.
- Sirat user data.
- Sirat business logic.
- Private route metrics or journey request history.

### Sirat API

Purpose:

- Plan journeys with mosque stops.
- Consume published directory data.
- Cache/sync directory data into its own database for fast planning.
- Submit corrections or stale-data observations back to the directory through public contribution APIs.

Does not own:

- Public mosque identity truth.
- Crawling.
- AI extraction.
- Partner feed ingestion.
- Public data governance.

## Names And Terms

- **Directory**: the public UK Jamaat Directory service.
- **Sirat API**: the private backend currently in this repo.
- **Directory Mosque ID**: stable public UUID/ULID assigned by the Directory.
- **Sirat Mosque ID**: private internal id in Sirat API. May map to one Directory Mosque ID.
- **Source**: an external origin: OSM, charity register, mosque website, MyLocalMasjid, Takbeer Time, Mawaqit URL/widget, CSV, mosque claim, community submission.
- **Source Artifact**: raw fetched evidence: HTML, PDF, image, JSON, CSV. Stored privately by the Directory, not published as bulk content.
- **Schedule Candidate**: extracted proposed timing pending validation/review.
- **Published Occurrence**: public normalized row for one mosque, one date, one prayer, one jamaat session.
- **Prayer Start**: adhan/start time.
- **Jamaat**: congregation time. Internal canonical term is `jamaat`; import aliases include `jamat`, `iqamah`, `iqama`.
- **Confidence**: public trust tier: `verified`, `official_import`, `partner_import`, `community`, `calculated`.
- **Freshness Status**: `fresh`, `stale`, `missing_today`, `missing_next_7_days`, `source_failed`, `needs_review`.

## Repository And Deployment Split

Create three separate code/data surfaces:

- `uk-jamaat-directory`: public-data service repo. Contains API, ingestion workers, extraction, moderation, public website, admin tooling.
- `uk-jamaat-contracts`: public schema repo/package. Contains OpenAPI spec, JSON Schemas, generated Python/TypeScript clients, dataset format docs.
- `sirat-api`: private proprietary repo. Adds only a Directory sync adapter and local read model.

Recommended visibility:

- Public: data exports, OpenAPI docs, JSON Schemas, changelog, attribution, source/freshness metadata.
- Private initially: crawler implementation, extraction prompts, moderation tooling, credentials, partner-feed adapters.
- Optional later: open-source non-sensitive Directory API/client code when operations are mature.

## Licensing And Governance

Use separate licenses:

- Directory normalized database: **ODbL 1.0**, because OSM-derived data is ODbL and the public directory will likely be an adapted database.
- Directory API docs/schemas: **CC BY 4.0**.
- Directory code: private initially; if opened later, use **AGPLv3** for service code or **Apache 2.0** for client libraries.
- Sirat API: remains proprietary.

Partner rule:

- MyLocalMasjid, Mawaqit, Masjidbox, or any other partner data can enter the public Directory only if the agreement permits normalized public redistribution under the Directory data license or a clearly compatible license.
- If a partner only allows private use, do **not** mix that data into the public Directory. Sirat may separately license it privately, but that becomes a Sirat-only proprietary source and must be clearly excluded from public exports.

Governance:

- Publish public attribution and correction policy.
- Provide mosque opt-out/correction flow.
- Keep private contact details for mosque claims out of public exports.
- Store raw website/PDF artifacts privately; publish normalized facts and source links only.

## External Data Strategy

Prioritize sources in this order:

1. **Mosque-owned feeds/claims**: most authoritative.
2. **MyLocalMasjid partnership**: highest-value initial partnership because they already state real jamaat schedules from 2,300+ UK masjids and provide masjid admin tooling.
3. **Other platform feeds**: Takbeer Time public API, Mawaqit direct URLs/widgets with permission, Masjidbox exports where available.
4. **Mosque websites**: HTML/PDF/image timetable extraction.
5. **OSM + charity registers**: excellent for discovery and identity, weak for jamaat times.
6. **Community submissions**: useful for coverage gaps, lower default confidence.
7. **Calculated times**: fallback only; never label as jamaat.

MyLocalMasjid partnership proposal:

- Ask for a UK mosque/timetable feed into the Directory, not into Sirat directly.
- Offer attribution, linkbacks, stale-data/correction reports, and optional Sirat journey-planning integration.
- Require explicit permission to republish normalized timetable facts publicly.
- If they decline public redistribution, continue without them for the public Directory and consider a separate Sirat-only commercial integration later.

## Directory Tech Stack

Backend:

- Python 3.12.
- FastAPI.
- Pydantic v2.
- SQLAlchemy async.
- Alembic.
- PostgreSQL 16 + PostGIS.
- Redis.
- Celery + Celery Beat.

Storage:

- S3-compatible object storage.
- MinIO locally.
- Cloudflare R2 or AWS S3 in production.

Crawling:

- `httpx` for normal fetches.
- Playwright fallback for dynamic pages.
- robots.txt enforcement.
- Per-domain crawl budgets.
- Sitemap discovery.
- ETag/Last-Modified/content-hash deduplication.

Parsing:

- `selectolax` or `lxml` for HTML.
- `pdfplumber`, `pypdf`, and `pymupdf` for PDFs.
- Tesseract OCR for scanned images.
- `rapidfuzz` for identity matching.

AI extraction:

- OpenAI Responses API with strict Structured Outputs.
- Vision-capable model configured by env var.
- AI outputs schedule candidates only; it never directly publishes rows.
- Keep prompts/versioning stored with `extractor_version`.

Frontend:

- Next.js App Router + TypeScript.
- Public directory website.
- Admin/moderation UI.
- Mosque claim/correction UI.
- Tailwind/shadcn-style component system is fine, but keep the admin UI dense and operational.

Observability:

- Sentry.
- Prometheus/Grafana.
- JSON logs.
- OpenTelemetry traces.
- Pipeline metrics: crawl success, extraction precision, stale mosques, missing next-7-days coverage, source failure rates.

## Directory Data Model

Core public tables:

- `mosques`: canonical public mosque records.
- `mosque_sources`: linked source identities.
- `mosque_aliases`: alternate names.
- `mosque_attributes`: facilities, madhab, affiliation, women’s space, parking, accessibility.
- `schedule_occurrences`: published per-date jamaat data.
- `dataset_versions`: immutable public export versions.
- `change_events`: append-only public changes feed.

Private operational tables:

- `source_artifacts`: raw fetched evidence.
- `extraction_runs`: parser/AI runs.
- `schedule_candidates`: extracted rows pending validation/review.
- `moderation_actions`: reviewer audit trail.
- `mosque_claims`: claimant identity and verification.
- `source_health`: crawl/import/freshness status.

Published occurrence fields:

```json
{
  "directory_mosque_id": "01J...",
  "date": "2026-06-05",
  "prayer": "fajr",
  "start_time": "02:48",
  "jamaat_time": "03:45",
  "session_number": 1,
  "session_label": null,
  "timezone": "Europe/London",
  "confidence": "verified",
  "source_type": "mosque_website",
  "source_url": "https://example.org/timetable",
  "last_verified_at": "2026-06-04T12:00:00Z",
  "freshness_status": "fresh"
}
```

## Directory Public APIs

Read APIs:

- `GET /v1/mosques`
- `GET /v1/mosques/search?q=&postcode=&city=&limit=`
- `GET /v1/mosques/{directory_mosque_id}`
- `GET /v1/mosques/{directory_mosque_id}/times?from=&to=`
- `GET /v1/times/nearby?lat=&lng=&radius_m=&date=`
- `GET /v1/changes?since=&limit=`
- `GET /v1/snapshots/latest?format=ndjson|csv`
- `GET /v1/snapshots/{version}`

Write/contribution APIs:

- `POST /v1/mosques/{id}/corrections`
- `POST /v1/mosques/{id}/schedule-submissions`
- `POST /v1/mosques/{id}/claims`
- `POST /v1/standard-feed/validate`

Admin APIs:

- `GET /v1/admin/candidates`
- `POST /v1/admin/candidates/{id}/approve`
- `POST /v1/admin/candidates/{id}/reject`
- `GET /v1/admin/sources`
- `PATCH /v1/admin/sources/{id}`
- `POST /v1/admin/mosques/{id}/merge`
- `GET /v1/admin/coverage`
- `GET /v1/admin/source-health`

Bulk exports:

- Daily NDJSON.
- Daily CSV.
- Full dump.
- Changes-only dump.
- Checksums and version metadata.
- Public attribution file.

## ~~Standard Mosque Feed~~ (retired)

The well-known JSON feed was considered but is not viable: most mosque websites will not
publish a machine-readable timetable at `/.well-known/uk-jamaat-directory.json`. The
crawl strategy is now **mosque_website** → AI profile (Phase 7) → deterministic
extraction (Phase 8). See ADR 0014.

<details>
<summary>Previous design (archived)</summary>

A public standard so mosques can publish their own feed:

- Path: `/.well-known/uk-jamaat-directory.json`
- Schema: mosque metadata + timezone + date-range + per-date prayer rows.
- The Directory would prefer this feed over scraping when present.

The feed schema definition was removed in Phase 12 of the remaining pipeline.
</details>

## Directory Pipeline

1. **Discover mosques**
   - Import OSM GB Muslim places of worship.
   - Import UK charity register datasets.
   - Import partner/platform data when licensed.
   - Accept community-created mosque candidates.

2. **Canonicalize identity**
   - Match by coordinates, postcode, normalized name, charity number, website domain, address, and known aliases.
   - Auto-link only high-confidence matches.
   - Queue ambiguous matches for moderation.

3. **Find schedule sources**
   - Official mosque website (crawl + AI profile).
   - Then partner API/feed.
   - Then PDF/image timetable.
   - Then community submissions.

4. **Fetch artifacts**
   - Respect robots.txt.
   - Store raw artifacts privately.
   - Skip unchanged content by hash.

5. **Extract candidates**
   - Deterministic parsers first.
   - OCR for scanned PDFs/images.
   - AI extraction for messy long tail.
   - Store evidence and extraction score.

6. **Validate**
   - Date validity.
   - Time format.
   - Prayer order.
   - Jamaat after prayer start.
   - Multiple Jummah sessions.
   - Ramadan timetable boundaries.
   - DST handling.
   - Comparison against calculated prayer windows as sanity check.

7. **Publish**
   - Auto-publish official/partner structured feeds when license and validation pass.
   - Auto-publish deterministic parser outputs only above high precision threshold.
   - Require human review for AI-only extraction until benchmark precision is proven.
   - Mark every row with source, confidence, and freshness.

8. **Monitor freshness**
   - Fresh: next 7 days covered.
   - Missing: today or next 7 days incomplete.
   - Stale: source not confirmed in 30 days.
   - Failed: 3 consecutive source failures.
   - Escalate to mosque, admin, or community.

## Linking Directory To Sirat API

Sirat should link to the Directory through a **read-only sync contract**, not a live planner dependency.

### Sirat Data Sync

Add a `DirectorySyncProvider` inside Sirat API:

- Fetches `GET /v1/changes?since=...` every hour.
- Fetches full snapshot daily as recovery.
- Validates responses using `uk-jamaat-contracts`.
- Upserts into Sirat local read tables.
- Records `directory_version`, `last_synced_at`, and `last_successful_sync_at`.

Sirat stores:

- `directory_mosque_id` on local mosque records.
- `directory_occurrence_id` or deterministic occurrence key.
- `directory_data_version`.
- `directory_confidence`.
- `directory_freshness_status`.
- `synced_at`.

Sirat does not store:

- Raw artifacts.
- Extraction runs.
- Moderation records.
- Mosque claim personal data.
- Partner-only restricted data unless separately licensed and clearly isolated.

### Sirat Planner Behavior

Planner reads local synced data only:

1. Query local synced exact-date jamaat occurrences.
2. Fall back to local legacy schedules if present.
3. Fall back to calculated Aladhan timing.
4. Return source/confidence in journey response.

No per-journey live calls to the Directory. This keeps Sirat fast and resilient.

### Sirat Correction Feedback

Sirat may send feedback upstream:

- `POST /v1/mosques/{id}/corrections` when users report wrong times.
- `POST /v1/mosques/{id}/schedule-submissions` for community timetable updates.
- `POST /v1/sync-clients/sirat/observations` for stale/missing data reports, if the Directory adds a signed client endpoint.

Sirat’s feedback should enter the same public Directory moderation flow as other contributions.

### Sirat API Public Responses

Sirat journey responses should include lightweight provenance:

```json
{
  "mosque": {
    "id": "sirat-private-id",
    "directory_id": "01J...",
    "name": "Example Masjid"
  },
  "jamaat": {
    "time": "2026-06-05T03:45:00+01:00",
    "confidence": "verified",
    "source": "uk_jamaat_directory",
    "directory_version": "2026-06-04.1"
  }
}
```

## Changes Needed In Sirat API

Keep changes deliberately small:

- Add Directory sync config:
  - `DIRECTORY_API_BASE_URL`
  - `DIRECTORY_SYNC_ENABLED`
  - `DIRECTORY_SYNC_INTERVAL_SECONDS`
  - `DIRECTORY_SNAPSHOT_URL`
  - `DIRECTORY_API_KEY`, optional for higher rate limits.
- Add local mirror tables for directory mosques and schedule occurrences.
- Add importer/sync service.
- Update `resolve_jamaat` to prefer synced exact-date occurrences.
- Add metrics:
  - last sync time
  - sync lag
  - rows imported
  - rows failed
  - directory coverage for journey candidates
- Keep existing admin schedule endpoints as emergency private overrides only.
- Remove any plan to add crawling/extraction/moderation to Sirat API.

## Rollout

### Phase 1: Public Directory Foundation

- Create `uk-jamaat-directory` and `uk-jamaat-contracts`.
- Build canonical mosque registry, source model, schedule occurrences, public read API, and bulk snapshots.
- Import OSM and charity register data.
- Publish first public dataset version.

### Phase 2: Sirat Link

- Add Directory sync adapter to Sirat.
- Mirror Directory mosques/times locally.
- Update planner to use exact-date Directory occurrences.
- Add sync health metrics.
- Keep Sirat’s current direct OSM/schedule importers as temporary fallback.

### Phase 3: Partnership And Claims

- Approach MyLocalMasjid for public-data partnership.
- Add mosque claim workflow.
- Add Takbeer Time adapter where terms permit.
- Add Mawaqit direct URL/widget adapter only with permission.
- Launch public correction flow.

### Phase 4: Crawling And Extraction

- Add respectful crawler and artifact store.
- Add HTML/PDF/OCR extraction.
- Add admin review queue.
- Publish only validated normalized rows.

### Phase 5: AI Extraction And Coverage Scale

- Add AI extraction for difficult artifacts.
- Build 50-100 mosque golden benchmark.
- Gate AI auto-publication until audited.
- Track coverage targets:
  - 2,000+ mosque records.
  - 500+ mosques with next-7-days jamaat by beta.
  - 1,500+ mosques with next-7-days jamaat by public launch.

### Phase 6: Standardization

- Promote `/.well-known/uk-jamaat-directory.json`.
- Provide mosque dashboard/export widgets.
- Encourage platforms to publish compatible feeds.
- Publish public monthly coverage reports.

## Test Plan

Directory tests:

- OSM/charity import identity matching.
- Partner feed imports.
- HTML/PDF/OCR parser fixtures.
- AI extraction schema validation.
- Schedule candidate validation.
- Multiple Jummah sessions.
- Ramadan timetable handling.
- DST boundary dates.
- Dataset snapshot generation.
- Public API pagination and rate limits.
- Attribution and license metadata.

Sirat tests:

- Directory snapshot sync.
- Incremental changes sync.
- Sync recovery after missed changes.
- Planner uses Directory occurrence before legacy schedule.
- Planner falls back to calculated timing when Directory has no jamaat.
- Journey response includes Directory provenance.
- Sirat remains functional if Directory API is temporarily unavailable.

Acceptance criteria:

- Sirat never calls the Directory live during a journey request.
- Directory data can be used by non-Sirat clients without knowing Sirat exists.
- Sirat can be redeployed privately without changing Directory data.
- Directory can publish new dataset versions without Sirat code changes if schemas remain compatible.
- Restricted partner data never leaks into public exports.
- Every published jamaat row has source, confidence, freshness, and dataset version.

## Assumptions

- The public Directory is a separate product, not a module inside Sirat API.
- Sirat API remains private and proprietary.
- Directory normalized data is public; raw artifacts and private contact details are not.
- MyLocalMasjid partnership is desirable but must permit public normalized redistribution to be part of the Directory.
- Sirat may optionally maintain separate private licensed data sources, but those must be isolated from the public Directory and clearly marked as proprietary.
- ODbL is the default public data license because OSM-derived data is part of the directory foundation.
