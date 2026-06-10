# GitHub Publishing Workflow

Phase 12 setup for the `SilentHacks/uk-jamaat-directory` repository.

## Already in place

| Item | Status | Location |
|------|--------|----------|
| Public GitHub repository | Done | [github.com/SilentHacks/uk-jamaat-directory](https://github.com/SilentHacks/uk-jamaat-directory) |
| CI on `master` and PRs | Done | [.github/workflows/ci.yml](../../.github/workflows/ci.yml) |
| PostGIS service container (no secrets) | Done | CI workflow `services.postgres` |
| Dependabot | Done | [.github/dependabot.yml](../../.github/dependabot.yml) |
| PR dependency review | Done | [.github/workflows/dependency-review.yml](../../.github/workflows/dependency-review.yml) |
| Code license (AGPL-3.0-or-later) | Done | [LICENSE.md](../../LICENSE.md) |
| Public data license (ODbL intent) | Done | [DATA_LICENSE.md](../../DATA_LICENSE.md) |
| Attribution policy | Done | [ATTRIBUTION.md](../../ATTRIBUTION.md) |
| Security reporting | Done | [SECURITY.md](../../SECURITY.md) |

Default branch is **`master`** (not `main`).

## CI workflow

CI runs on every push to `master` and on pull requests targeting `master`:

1. Ruff lint
2. Production compose config validation (`make compose-production-config`)
3. `alembic upgrade head` against a PostGIS service container
4. Full pytest suite with `UK_JAMAAT_TEST_POSTGRES=1`

No repository secrets are required. The workflow uses GitHub's PostGIS service container on
port 5432 inside the job.

Local equivalent:

```bash
make test-postgres
```

## Branch protection

Enable branch protection on `master` once CI is reliable:

- Require status check **CI / lint-and-test** (or the full job name as shown in GitHub)
- Require pull request reviews before merge (recommended for multi-maintainer work)
- Disallow force pushes to `master`
- Optionally require branches to be up to date before merge

### Manual setup (GitHub UI)

1. Repository → **Settings** → **Branches**
2. **Add branch protection rule** for `master`
3. Enable **Require status checks to pass before merging**
4. Select the **CI** workflow job
5. Save the rule

### CLI setup

```bash
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  repos/SilentHacks/uk-jamaat-directory/branches/master/protection \
  -f required_status_checks[strict]=true \
  -f required_status_checks[contexts][]='lint-and-test' \
  -f enforce_admins=true \
  -f required_pull_request_reviews[required_approving_review_count]=1 \
  -f restrictions=null
```

Adjust the status check context name to match the job name shown in the Actions tab.

## Dependabot

Dependabot opens monthly PRs for:

- **pip** dependencies in `pyproject.toml` (minor/patch grouped)
- **github-actions** workflow pins

Review and merge Dependabot PRs after CI passes. Security advisories may arrive outside the
monthly schedule.

## Before a public data release

Publish or link these documents when releasing public dataset files:

- [DATA_LICENSE.md](../../DATA_LICENSE.md)
- [ATTRIBUTION.md](../../ATTRIBUTION.md)

Update export metadata and an ADR with the effective publication date when the first public
snapshot ships.

## Related ADR

- [0001: Public Directory With Private Operations](../adr/0001-public-directory-private-operations.md)
- [0010: GitHub Publishing Workflow](../adr/0010-github-publishing-workflow.md)
