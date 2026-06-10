# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| `0.1.x` (current development) | Yes |

Security fixes are applied on the `master` branch. Deploy from tagged releases or recent
`master` commits when operating a production VPS.

## Reporting a vulnerability

Please do **not** open public GitHub issues for security-sensitive reports.

Report vulnerabilities privately to the repository maintainers:

1. Use GitHub **Private vulnerability reporting** if enabled on the repository, **or**
2. Email the maintainers directly using the contact address configured for the
   `SilentHacks/uk-jamaat-directory` organization.

Include:

- Description of the issue and affected components (API, admin routes, ingest, exports)
- Steps to reproduce
- Impact assessment (data exposure, authentication bypass, SSRF, etc.)
- Any suggested fix or mitigation

We aim to acknowledge reports within **5 business days** and provide a remediation plan or
status update within **30 days** for confirmed issues.

## Scope

In scope:

- Public `/v1` read API and documented admin routes
- Authentication and authorization for admin operations
- Source ingestion, crawl/fetch SSRF protections, and object-storage access
- Export generation and public/private field boundaries
- Deployment configuration that could expose private data

Out of scope:

- Denial-of-service attacks against a privately operated VPS without a demonstrated
  application defect
- Social engineering against mosque claimants or operators
- Issues in third-party services (Postgres, Redis, MinIO, Caddy) unless introduced by our
  configuration defaults

## Safe harbor

Good-faith security research on staging environments or with maintainers' written permission
is welcome. Do not access production data you are not authorized to use, and do not exfiltrate
partner artifacts or claimant contact details.

## Dependency updates

Runtime dependency updates are monitored through Dependabot (see `.github/dependabot.yml`).
Apply security-related dependency PRs promptly after CI passes.
