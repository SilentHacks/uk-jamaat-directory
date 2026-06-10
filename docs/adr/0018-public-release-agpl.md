# 0018: Public Release And AGPL Relicensing

- Status: accepted
- Date: 2026-06-10

## Context

The repository was developed privately under a proprietary all-rights-reserved license
(ADR 0010 recorded "code remains proprietary until an explicit future relicensing
decision"). The project is now being made publicly visible on GitHub as an open-source
project.

## Decision

1. The repository becomes **public** on GitHub.
2. Application source code is relicensed under the **GNU Affero General Public License,
   version 3 or later (AGPL-3.0-or-later)**. AGPL was chosen over permissive licenses so
   that anyone operating a modified copy of the Directory as a network service must share
   their changes.
3. Public dataset licensing is unchanged: intended **ODbL 1.0** per
   [DATA_LICENSE.md](../../DATA_LICENSE.md); no public data release has occurred yet.
4. Security reporting moves to GitHub private vulnerability reporting / maintainer contact
   (see [SECURITY.md](../../SECURITY.md)); reports must not be filed as public issues.

## Consequences

- `LICENSE.md` now carries the AGPLv3 text; `pyproject.toml` declares
  `AGPL-3.0-or-later`.
- Docs no longer describe the repository as private (README, SECURITY, deploy and GitHub
  workflow docs updated). Earlier ADRs are historical records and were not rewritten.
- Private operational data rules are unaffected: raw artifacts, claim contact details,
  discovery leads, and restricted partner data stay out of the repository and public
  exports (ADR 0001, ADR 0003).
