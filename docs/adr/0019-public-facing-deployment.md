# 0019: Public-Facing Deployment

- Status: accepted
- Date: 2026-06-11

## Context

The repository was hardened for open sourcing (ADR 0018) but had no public face: the
API had no landing page, OpenAPI/Swagger were fully disabled in production, the reverse
proxy set no security headers or body limits, production images were built on the VPS,
rate limiting covered only community submissions, and there was no error tracking. The
goal of this change is to make the Directory deploy-ready and presentable to the public
(landing page, viewable API reference, hardened serve/deploy pipeline) without pulling
forward the full directory-browsing frontend (roadmap item 6).

## Decision

1. **Static public site, served by Caddy.** A landing page, an interactive API
   reference, and a bulk-data listing live in `web/public/` and are served by Caddy
   `file_server` from a read-only bind mount. No Node toolchain; content updates ship
   with `git pull` + reload, not an image rebuild. The JSON API stays HTML-free.

2. **Public OpenAPI re-enabled, admin filtered out.** A filtered spec is served at
   `/v1/openapi.json` in every environment; operations carrying the `admin` OpenAPI tag
   and their unreferenced component schemas are pruned. The full spec and Swagger UI move
   to `/internal/*`, off in production by default. `make export-contracts` writes the
   same filtered spec, so the committed `docs/api/openapi.json`, the live route, and the
   reference UI share one source of truth. Convention: routes that must stay private
   carry the `admin` tag.

3. **Self-hosted Scalar** (vendored, no CDN) renders the reference from the live spec,
   satisfying a strict `script-src 'self'` CSP and removing a supply-chain dependency.

4. **GHCR images, manual deploy.** CI builds and pushes `sha-<sha>` + `latest` images to
   GHCR; the VPS pulls and never builds. Deploys are triggered manually
   (`workflow_dispatch`) over SSH because migrations run against the single production
   database. Rollback = redeploy the previous `sha-<sha>` tag; if a migration was
   involved, restore the pre-deploy `pg_dump` first (alembic downgrades are not relied
   on).

5. **Serve hardening at the edge and the app.** Caddy sets HSTS, `X-Content-Type-Options`,
   `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, a per-page CSP, zstd+gzip,
   a 1 MB body cap, and server timeouts. The app adds a global per-IP sliding-window
   rate limit over all public traffic (health checks exempt), defaults CORS to `*` with
   credentials off (correct for a public read API; admin is gated by `X-Admin-Key`), and
   sets `Cache-Control` on public reads.

6. **Minimal observability.** Sentry is wired into the API and Celery, inert unless
   `SENTRY_DSN` is set. External uptime monitoring targets `/v1/health/ready`.

## Consequences

- **Rate limiting stays in-process.** Exact for the single-process, single-VPS topology;
  it must move to a shared store (e.g. Redis) before the API is scaled to multiple
  workers or instances.
- **Published policies.** Public rate limit (120 req/min/IP) and the submission limit
  (10/min) are documented in `docs/api/README.md` alongside an API versioning statement,
  resolving two PLAN.md open decisions.
- **Deliberately deferred:** a `/metrics` endpoint (nothing scrapes it yet), ETag
  revalidation, Caddy-level response caching, and HSTS `preload`/`includeSubDomains`
  (hard to reverse). Revisit when traffic or topology justifies them.
- The Caddy `rate_limit` module was rejected (third-party, needs a custom xcaddy build);
  the stock `caddy:2-alpine` image is retained.
- The full (admin-inclusive) spec is no longer committed anywhere; it is reachable in
  development at `/internal/openapi.json`.
