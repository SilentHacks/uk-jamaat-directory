# 0001: Public Directory With Private Operations

## Status

Accepted.

## Context

The Directory is intended to provide public mosque and jamaat timetable data. The same system also needs operational machinery that should not be public by default: crawlers, raw artifacts, extraction prompts, moderation notes, source credentials, and mosque claim contact details.

The code repository is private initially and may become partly public later.

## Decision

Build a single private service repository for the initial implementation, but keep a strict boundary between public data contracts and private operational implementation.

Public surfaces include:

- Versioned read APIs.
- OpenAPI and JSON schema documentation.
- Bulk snapshot formats.
- Dataset metadata, freshness, confidence, and attribution.

Private surfaces include:

- Raw source artifacts.
- Crawler and extraction internals.
- Source credentials and partner adapters.
- Moderation notes and claimant personal data.
- Admin-only workflows.

## Consequences

The implementation can move quickly while preserving a clean path to publish schemas, docs, generated clients, or selected code later.

Public/private field separation must be tested. Export and response models should be explicit rather than reusing database models directly.
