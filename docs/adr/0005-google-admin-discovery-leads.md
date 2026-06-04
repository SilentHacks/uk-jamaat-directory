# 0005: Google Discovery Leads Are Admin-Only

## Status

Accepted.

## Context

Phase 6 discovery may use Google Maps/Places to help operators find missing mosques. Google content is not licensed for unrestricted public redistribution in the same way as OSM.

## Decision

Google is used only as an admin-facing lead-generation and verification aid. The Directory must not store or publish Google-derived mosque facts as public provenance. Final accepted facts should be entered via manual/admin sources or linked to permitted public sources such as OSM.

## Consequences

- Admin endpoints may record private discovery leads in moderation audit metadata.
- No `mosque_sources` rows with public Google attribution.
- Future Google API integration remains optional and private.
