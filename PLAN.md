# UK Jamaat Directory — Product Plan

This document owns the product vision, source strategy, coverage targets, and forward
roadmap. It deliberately does **not** restate implemented design:

- Implemented architecture and decisions → [docs/adr/](docs/adr/)
- Domain language and publication invariants → [CONTEXT.md](CONTEXT.md)
- Current commands, scope, and conventions → [README.md](README.md) / [AGENTS.md](AGENTS.md)

When a section here gets built, record the decision in an ADR and shrink the section to a
pointer. Sections that turned out wrong are archived at the bottom, not silently deleted.

## Vision

A public data utility containing UK mosque identities, source provenance, jamaat timetable
occurrences, freshness status, public read APIs, and bulk exports — useful to any Muslim
app, community tool, or researcher. **Public data service first; every consumer (including
Sirat) is just a client.**

## Product Boundary

The Directory owns: canonical mosque identity, source provenance, schedule candidates,
published occurrences, freshness, moderation/claims/corrections workflows, and bulk
exports.

The Directory does not own: journey planning, routing, any consumer's user data or
business logic. Consumers sync from snapshots and change feeds; they must not call the
Directory live on their own request paths, and they must not embed crawler, extraction,
or moderation infrastructure (see ADR 0001).

**Sirat** (a private journey-planning product, maintained in its own repository) is the
first consumer. Its sync adapter, mirror tables, and planner fallback behavior are
designed and documented in the `sirat-api` repository. The contract it relies on from
this side:

- `GET /v1/changes?since=` for incremental sync, snapshots for full recovery.
- Provenance fields (`confidence`, `freshness_status`, `source_type`, dataset version) on
  every published row.
- Public contribution APIs (`corrections`, `schedule-submissions`) for feedback, entering
  the same moderation flow as any other contributor.

## Source Strategy

Priority order for jamaat times:

1. **Mosque-owned feeds/claims** — most authoritative.
2. **MyLocalMasjid partnership** — highest-value initial partnership (~2,300+ UK masjids
   with real jamaat schedules). Requires explicit permission for public normalized
   redistribution; without it, MLM data stays out of public exports entirely.
3. **Other platform feeds** — Takbeer Time, Mawaqit, Masjidbox — only with permission.
   Mosque pages embedding these widgets are extracted as mosque-website sources
   (trusted widget hosts, ADR 0017 / domain policy).
4. **Mosque websites** — repo-owned deterministic extractor scripts authored by the
   overnight AI orchestrator (ADRs 0016/0017). HTML and PDF tables are live; OCR for
   image timetables is stubbed pending implementation.
5. **OSM + charity registers** — discovery and identity only; never jamaat times.
6. **Community submissions** — coverage gaps, lower default confidence.
7. **Calculated times** — fallback only; never labeled as jamaat (enforced by semantic
   output checks).

Aggregator/directory sites are never timetable sources; multi-mosque umbrella sites go to
a manual review queue (domain policy module).

## Licensing and Governance

Decided and recorded:

- Code: **AGPL-3.0-or-later** (ADR 0018, [LICENSE.md](LICENSE.md)).
- Public normalized data: intended **ODbL 1.0** ([DATA_LICENSE.md](DATA_LICENSE.md));
  no public data release yet.
- API docs/schemas: **CC BY 4.0** when published separately.
- Attribution and security policy: [ATTRIBUTION.md](ATTRIBUTION.md),
  [SECURITY.md](SECURITY.md).

Standing partner rule: partner data enters the public Directory only when the agreement
permits normalized public redistribution under a compatible license. Private-use-only
partner data never mixes into public exports.

## Coverage Targets and Status

Targets (set at project start, unchanged):

| Milestone | Target |
|-----------|--------|
| Mosque identity records | 2,000+ |
| Mosques with next-7-days jamaat at beta | 500+ |
| Mosques with next-7-days jamaat at public launch | 1,500+ |

Status (2026-06-10, dev database):

| Metric | Current |
|--------|---------|
| Active mosque records | 2,420 ✅ |
| `mosque_website` sources registered | 1,843 |
| Deployed extractor scripts | 0 (reset 2026-06-10; re-authoring pending) |
| Mosques with published occurrences | 0 (no publish run yet) |
| Sources permanently closed (dead site / no jamaat / aggregator / robots) | ~300 classified |

Update this table after each significant authoring/publish run; once exports go live,
replace it with the public coverage report.

## Roadmap

Phases 0–12 are implemented (see README progress table): scaffold, schema, public read
API, MLM/OSM/MiB imports, identity matching, validation/publication, admin moderation,
crawl, bulk exports, VPS deployment, GitHub hygiene — plus the repo-owned extractor
pipeline and overnight authoring orchestrator (ADRs 0016/0017), and the public-facing
deployment layer: static landing/docs/data site, public API reference, edge + app
hardening, and a GHCR build/deploy pipeline (ADR 0019).

Forward roadmap, in order:

1. **Extraction coverage**: full overnight authoring run over the 1,843 website sources;
   triage the review queue (umbrella sites, PDF/image targets); first real
   validate → publish → export cycle.
2. **OCR for image/scanned timetables**: replace the OCR stub; gate behind the same
   smoke-test and semantic checks.
3. **First public dataset release**: publish snapshot + ODbL effective date (record in an
   ADR per DATA_LICENSE.md); publish the coverage report.
4. **MyLocalMasjid partnership approach**: formal ask for public-redistribution
   permission, attribution and correction-report offer.
5. **Sirat sync adapter** (in `sirat-api`): consumes changes/snapshots; first proof of
   the consumer contract. Decide then whether generated API clients warrant a separate
   contracts package (see open decisions).
6. **Frontend**: full directory-browsing website and admin/moderation UI (Next.js per
   original intent — revalidate the stack when work starts). The static landing page,
   API reference, and bulk-data listing already exist (ADR 0019); this item is now the
   interactive mosque search/browse experience and the moderation UI only.
7. **Platform feed adapters** (Takbeer Time, Mawaqit direct) where terms permit.

## Open Decisions

Explicitly undecided — decide when the trigger fires, then ADR it:

- **Contracts packaging**: contracts stay in-repo (`docs/api/`, `make export-contracts`)
  until a real external consumer needs a typed client. Then decide: generated package
  from this repo vs. separate `uk-jamaat-contracts` repo (relevant if clients should be
  Apache-2.0 while the service is AGPL).
- **API versioning/deprecation policy**: decided — `/v1` is stable and additive-only;
  breaking changes get a new prefix with a ≥90-day parallel window; dataset schema
  versions ride snapshot metadata (ADR 0019, [docs/api/README.md](docs/api/README.md)).
  An optional API-key tier is still open.
- **Public rate-limit policy**: decided and published — 120 req/min/IP public, 10/min
  submissions (ADR 0019). The in-process limiter must move to a shared store before
  scaling to multiple workers/instances.
- **Observability**: minimal set decided (ADR 0019) — Sentry (optional via DSN) plus
  external uptime monitoring on `/v1/health/ready`; JSON logs as before. A `/metrics`
  endpoint and OTel remain deferred until traffic justifies them.

## Test Expectations

Regression areas that must stay covered as features land: identity matching, partner
imports, extractor validation gates (static, smoke, semantic), multiple Jumu'ah sessions,
Ramadan timetables, DST boundaries, snapshot determinism, publication-policy filtering,
attribution metadata. See AGENTS.md for the testing workflow.

Acceptance criteria that define success regardless of phase:

- Directory data is usable by any client without knowing other consumers exist.
- Restricted partner data never leaks into public exports.
- Every published jamaat row has source, confidence, freshness, and dataset version.
- Consumers never call the Directory live on their own request paths.

---

## Archived sections

<details>
<summary>Per-fetch AI extraction (superseded by ADRs 0016/0017)</summary>

The original plan called for OpenAI Responses API with strict Structured Outputs to
extract schedule candidates from messy artifacts on every fetch, gated behind a 50–100
mosque golden benchmark before auto-publication.

This was replaced by a different architecture: an overnight AI agent **authors
deterministic, repo-owned extractor scripts once per source** (validated by static
checks, an execution smoke test, and semantic output checks); the scheduled runtime then
runs those scripts sandboxed with no network or AI involvement. Cheaper per fetch, fully
auditable, and deterministic. See ADR 0016 (repo-owned extractor scripts) and ADR 0017
(overnight authoring orchestrator).

</details>

<details>
<summary>Standard Mosque Feed `/.well-known/uk-jamaat-directory.json` (retired, ADR 0014)</summary>

A public standard so mosques could publish their own machine-readable feed. Not viable:
most mosque websites will not publish one. The crawl + extractor-script strategy replaced
it. A mosque-owned structured feed may return as a future idea if platform partnerships
make it cheap for mosques to emit.

</details>

<details>
<summary>Sirat implementation detail (moved to the sirat-api repository)</summary>

Earlier revisions of this document specified Sirat's internal sync provider, mirror
tables, environment variables, planner fallback order, and response provenance shapes.
That is another product's implementation detail and now lives in the private `sirat-api`
repository. The Directory-side contract Sirat relies on is summarized under **Product
Boundary** above.

</details>
