from __future__ import annotations

from enum import StrEnum


class SourcePublicationPolicy(StrEnum):
    PUBLIC_REDISTRIBUTION_ALLOWED = "public_redistribution_allowed"
    PRIVATE_USE_ONLY = "private_use_only"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class SourceType(StrEnum):
    MYLOCALMASJID = "mylocalmasjid"
    MOSQUE_WEBSITE = "mosque_website"
    OPENSTREETMAP = "openstreetmap"
    MUSLIMSINBRITAIN = "muslimsinbritain"
    CHARITY_REGISTER = "charity_register"
    OSCR_REGISTER = "oscr_register"
    COMMUNITY = "community"
    MANUAL = "manual"
    PARTNER_FEED = "partner_feed"


class Confidence(StrEnum):
    VERIFIED = "verified"
    OFFICIAL_IMPORT = "official_import"
    PARTNER_IMPORT = "partner_import"
    COMMUNITY = "community"
    CALCULATED = "calculated"


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING_TODAY = "missing_today"
    MISSING_NEXT_7_DAYS = "missing_next_7_days"
    SOURCE_FAILED = "source_failed"
    NEEDS_REVIEW = "needs_review"


class Prayer(StrEnum):
    FAJR = "fajr"
    DHUHR = "dhuhr"
    ASR = "asr"
    MAGHRIB = "maghrib"
    ISHA = "isha"
    JUMUAH = "jumuah"


class MosqueStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    NEEDS_REVIEW = "needs_review"
    DUPLICATE = "duplicate"


class CandidateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ArtifactStatus(StrEnum):
    FETCHED = "fetched"
    UNCHANGED = "unchanged"
    FAILED = "failed"


class ExtractionKind(StrEnum):
    DETERMINISTIC = "deterministic"
    OCR = "ocr"
    AI = "ai"
    MANUAL = "manual"


class ClaimStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    REVOKED = "revoked"


class CorrectionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ChangeEventType(StrEnum):
    MOSQUE_CREATED = "mosque_created"
    MOSQUE_UPDATED = "mosque_updated"
    OCCURRENCE_PUBLISHED = "occurrence_published"
    OCCURRENCE_REMOVED = "occurrence_removed"
    SOURCE_UPDATED = "source_updated"
