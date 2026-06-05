# 0010: GitHub Publishing Workflow

## Status

Accepted.

## Context

The Directory is developed in a private GitHub repository while public data contracts and
licensing are prepared for a future release. Phase 12 requires CI, dependency hygiene, legal
docs, and a path to branch protection without committing secrets.

Items already completed before this ADR: private repo creation, baseline push, and CI with a
PostGIS service container on `master`.

## Decision

1. **Default branch `master`** — CI workflows target `master` for pushes and pull requests.

2. **Secretless CI** — GitHub Actions uses a PostGIS service container and environment
   variables for `DATABASE_URL` / `TEST_DATABASE_URL`. No repository secrets for tests.

3. **Dependabot** — Monthly pip and github-actions update PRs via `.github/dependabot.yml`.

4. **Dependency review on PRs** — Fail PRs that introduce dependencies with high-severity
   advisories (`.github/workflows/dependency-review.yml`).

5. **Separate license documents** before any public data release:
   - `LICENSE.md` — proprietary application code (private repo)
   - `DATA_LICENSE.md` — intended ODbL 1.0 for public normalized database exports
   - `ATTRIBUTION.md` — required credits for Directory and upstream sources
   - `SECURITY.md` — private vulnerability reporting process

6. **Branch protection** — Document manual setup in `docs/github/README.md`. Enabling rules
   on private repos may require GitHub Pro; operators enable when the account plan allows.

7. **API schemas** — When published separately, `docs/api/` is intended under CC BY 4.0
   (documented in `DATA_LICENSE.md`, not relicensed inside the private repo automatically).

## Consequences

- Contributors rely on CI and Dependabot PRs for quality and dependency hygiene.
- Public data consumers have clear license and attribution docs before exports ship.
- Code remains proprietary until an explicit future relicensing decision.
- Branch protection is an operator step, not enforced by this repository's files alone.
