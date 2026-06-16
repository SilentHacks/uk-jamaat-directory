# ADR 0020: Server-rendered dashboard and admin UI

- Status: Accepted
- Date: 2026-06-16

## Context

The public site was a static landing page plus the Scalar API reference and a
bulk-data listing. We want the site to become a usable product surface:

- a public, unauthenticated way to **search, filter, and browse** mosques and view
  their **weekly jamaat timetables**;
- a **key-gated admin** area to manage mosque entities, source publication policy,
  schedule moderation/publication, and the crawl/extraction pipeline.

The backend already exposes the needed reads (`services/public_reads`) and admin
operations (`services/admin_*`, `schedule_moderation`, `admin_reporting`) and a
JSON admin API under `/v1/admin` guarded by `X-Admin-Key`.

## Decision

Build the UI as **server-rendered Jinja2 templates with HTMX**, inside the existing
FastAPI app, in a dedicated `uk_jamaat_directory.ui` package. The UI calls the
`services/` layer directly rather than round-tripping through `/v1`.

- **No Node/bundler.** Templates render server-side; HTMX (`htmx.min.js`, vendored
  under `web/public/assets/`) provides partial updates. No Alpine.js, so the strict
  `script-src 'self'` CSP is preserved (htmx is same-origin and needs no `eval`).
- **Routing.** Caddy serves `/assets/*`, `/docs`, `/data`, and `/exports/*` as
  before; `/v1/*` is the JSON API; everything else (`/`, `/mosques/*`, `/about`,
  `/admin/*`) is reverse-proxied to the API, which renders HTML. The landing page is
  now the mosque search dashboard; the former marketing/API content moved to
  `/about`.
- **Admin auth.** A single shared-key login (`/admin/login`) verifies the existing
  `ADMIN_API_KEY` with a constant-time compare and establishes a signed session
  cookie (Starlette `SessionMiddleware`, keyed by `SESSION_SECRET_KEY`). Every
  state-changing admin POST carries a CSRF token stored in the session. The admin UI
  is enabled only when **both** `SESSION_SECRET_KEY` and `ADMIN_API_KEY` are set.
- **Pipeline actions** (publish/validate/recompute-freshness, per-source crawl) are
  dispatched to Celery (`tasks/schedules.py`, `tasks/crawl.py`) so requests never
  block on long operations.
- **The `/v1` JSON API stays a pure machine contract.** UI routes set
  `include_in_schema=False` and are excluded from the public OpenAPI spec.

## Alternatives considered

- **Decoupled static JS SPA calling `/v1`.** Keeps static deployment but hand-rolls
  routing/state and makes cookie-session admin awkward against a header-keyed JSON
  API. Rejected as more client code for less benefit.
- **SPA framework (React/Svelte/Astro).** Best DX but adds a Node toolchain, bundler,
  and CSP friction. Rejected against the "lean/simple" goal.
- **Per-user accounts + RBAC.** Overkill for a single-operator tool today; the
  shared-key session can be upgraded later without changing the UI structure.

## Consequences

- The app now serves HTML as well as JSON, isolated in the `ui` package; the `/v1`
  boundary is unchanged.
- New runtime deps: `jinja2`, `itsdangerous`, `python-multipart`.
- `SESSION_SECRET_KEY` must be set in production `.env` to enable admin login.
- Map view is explicitly out of scope (no tile dependency / CSP relaxation).
