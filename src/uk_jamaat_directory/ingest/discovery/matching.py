from __future__ import annotations

import math
import re

from geoalchemy2.shape import to_shape
from rapidfuzz import fuzz
from shapely.geometry import Point

from uk_jamaat_directory.ingest.discovery.records import (
    DiscoveryMatch,
    DiscoveryRecord,
    MatchDecision,
    ScoredMosqueCandidate,
)
from uk_jamaat_directory.ingest.normalize import (
    normalize_city,
    normalize_domain,
    normalize_mosque_name,
    normalize_postcode,
)
from uk_jamaat_directory.models.core import Mosque, MosqueAlias

AUTO_LINK_THRESHOLD = 0.75
STRONG_NAME_RATIO = 92
NAME_OVERRIDE_RATIO = 85
NAME_OVERRIDE_MAX_GAP = 0.25
PARENT_ORG_PENALTY = 0.20
GEO_IDENTITY_METERS = 25
NEARBY_METERS = 150
GEO_CANDIDATE_METERS = 500

_PARENT_ORG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwelfare\s+association\b", re.IGNORECASE),
    re.compile(r"\beducation\s+society\b", re.IGNORECASE),
    re.compile(r"\beducation\s+trust\b", re.IGNORECASE),
    re.compile(r"\borganisation\b", re.IGNORECASE),
    re.compile(r"\borganization\b", re.IGNORECASE),
    re.compile(r"\bcharity\b", re.IGNORECASE),
    re.compile(r"\bfalah\s+education\b", re.IGNORECASE),
)


def score_mosque_candidate(
    record: DiscoveryRecord,
    mosque: Mosque,
    *,
    aliases: list[MosqueAlias] | None = None,
) -> ScoredMosqueCandidate | None:
    reasons: list[str] = []
    score = 0.0
    signals = 0

    record_postcode = normalize_postcode(record.postcode)
    mosque_postcode = normalize_postcode(mosque.postcode)
    if record_postcode and mosque_postcode and record_postcode == mosque_postcode:
        score += 0.35
        signals += 1
        reasons.append("postcode_match")

    record_name = normalize_mosque_name(record.name)
    mosque_name = mosque.normalized_name
    name_ratio = fuzz.token_sort_ratio(record_name, mosque_name)
    if name_ratio >= STRONG_NAME_RATIO:
        score += 0.30
        signals += 1
        reasons.append(f"name_ratio_{int(round(name_ratio))}")
    elif name_ratio >= 85:
        score += 0.15
        reasons.append(f"name_ratio_{int(round(name_ratio))}")

    if aliases:
        for alias_row in aliases:
            alias_ratio = fuzz.token_sort_ratio(record_name, alias_row.normalized_alias)
            if alias_ratio >= STRONG_NAME_RATIO:
                score += 0.20
                signals += 1
                reasons.append(f"alias_ratio_{int(round(alias_ratio))}")
                break

    record_domain = normalize_domain(record.website_url)
    mosque_domain = normalize_domain(mosque.website_url)
    if record_domain and mosque_domain and record_domain == mosque_domain:
        score += 0.25
        signals += 1
        reasons.append("domain_match")

    record_city = normalize_city(record.city)
    mosque_city = normalize_city(mosque.city)
    if record_city and mosque_city and record_city == mosque_city:
        score += 0.10
        reasons.append("city_match")

    lat, lon = mosque_coordinates(mosque)
    distance_m = distance_meters(record.latitude, record.longitude, lat, lon)
    geo_score, geo_signals, geo_reasons = _geo_score(
        distance_m,
        allow_identity=_allows_geo_identity(record),
    )
    if geo_score:
        score += geo_score
        signals += geo_signals
        reasons.extend(geo_reasons)

    best_name_ratio = max(
        [
            ratio
            for reason in reasons
            if (ratio := _fuzzy_ratio_from_reason(reason)) is not None
        ],
        default=0,
    )
    if _is_parent_org_name(record.name) and best_name_ratio < NAME_OVERRIDE_RATIO:
        score -= PARENT_ORG_PENALTY
        reasons.append("parent_org_source")

    if score < 0.25:
        return None

    reasons.append(f"signals_{signals}")
    return ScoredMosqueCandidate(mosque_id=mosque.id, score=min(score, 1.0), reasons=reasons)


def decide_match(
    record: DiscoveryRecord,
    candidates: list[ScoredMosqueCandidate],
) -> DiscoveryMatch:
    if not candidates:
        return DiscoveryMatch(
            decision=MatchDecision.CREATE_NEEDS_REVIEW,
            reasons=["no_existing_mosque_candidates"],
        )

    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    override_idx = _name_evidence_override(ranked)
    override_applied = False
    if override_idx is not None:
        promoted = ranked.pop(override_idx)
        ranked.insert(0, promoted)
        override_applied = True
    best = ranked[0]

    if len(ranked) > 1 and ranked[1].score >= 0.5 and (best.score - ranked[1].score) < 0.1:
        reasons_list = ["ambiguous_multiple_candidates"]
        if override_applied:
            reasons_list.append("name_evidence_override")
        return DiscoveryMatch(
            decision=MatchDecision.NEEDS_REVIEW,
            score=best.score,
            reasons=reasons_list,
            alternatives=ranked[:3],
        )

    strong_signals = _count_strong_signals(best.reasons)
    if (
        best.score >= AUTO_LINK_THRESHOLD
        and strong_signals >= 2
        and _has_identity_signal(best.reasons)
    ):
        return DiscoveryMatch(
            decision=MatchDecision.AUTO_LINK,
            mosque_id=best.mosque_id,
            score=best.score,
            reasons=best.reasons,
        )

    if best.score >= AUTO_LINK_THRESHOLD:
        reasons_list = ["high_score_insufficient_signals", *best.reasons]
        if override_applied:
            reasons_list.insert(0, "name_evidence_override")
        return DiscoveryMatch(
            decision=MatchDecision.NEEDS_REVIEW,
            score=best.score,
            reasons=reasons_list,
            alternatives=ranked[:3],
        )

    if best.score >= 0.25:
        reasons_list = ["below_auto_link_threshold", *best.reasons]
        if override_applied:
            reasons_list.insert(0, "name_evidence_override")
        return DiscoveryMatch(
            decision=MatchDecision.NEEDS_REVIEW,
            score=best.score,
            reasons=reasons_list,
            alternatives=ranked[:3],
        )

    return DiscoveryMatch(
        decision=MatchDecision.CREATE_NEEDS_REVIEW,
        score=best.score,
        reasons=["below_auto_link_threshold", *best.reasons],
    )


def _fuzzy_ratio_from_reason(reason: str) -> int | None:
    if reason.startswith("name_ratio_"):
        suffix = reason.removeprefix("name_ratio_")
    elif reason.startswith("alias_ratio_"):
        suffix = reason.removeprefix("alias_ratio_")
    else:
        return None
    try:
        return int(suffix)
    except ValueError:
        return None


def _highest_name_ratio(reasons: list[str]) -> int:
    return max(
        (ratio for reason in reasons if (ratio := _fuzzy_ratio_from_reason(reason)) is not None),
        default=0,
    )


def _name_evidence_override(ranked: list[ScoredMosqueCandidate]) -> int | None:
    """Return the index of a candidate to promote to the top of `ranked`.

    The override applies when the highest-scoring candidate has no name
    evidence at all but a lower-ranked candidate shares a meaningful
    portion of the name. This protects against the case where a
    geo+postcode-only candidate outranks a name-matching candidate just
    because it happens to be closer.
    """
    if len(ranked) < 2:
        return None
    if _highest_name_ratio(ranked[0].reasons) >= NAME_OVERRIDE_RATIO:
        return None
    top = ranked[0]
    for idx, alt in enumerate(ranked[1:], start=1):
        if _highest_name_ratio(alt.reasons) < NAME_OVERRIDE_RATIO:
            continue
        if top.score - alt.score > NAME_OVERRIDE_MAX_GAP:
            return None
        return idx
    return None


def _is_parent_org_name(name: str | None) -> bool:
    """Return True if `name` looks like a parent organisation rather than a venue.

    These are records that share a building with a real mosque but are not
    the mosque itself (e.g. "Islamic Cultural Welfare Association",
    "Falah Education Society", "IMAM Organisation UK"). When the source
    has such a name and there is no name match with the candidate, the
    score is penalised so the matcher does not auto-link them.
    """
    if not name:
        return False
    return any(pattern.search(name) for pattern in _PARENT_ORG_PATTERNS)


def _count_strong_signals(reasons: list[str]) -> int:
    count = 0
    for reason in reasons:
        if reason.startswith(("postcode_", "distance_", "geo_identity_")):
            count += 1
        elif reason.startswith("domain_"):
            count += 1
        else:
            ratio = _fuzzy_ratio_from_reason(reason)
            if ratio is not None and ratio >= STRONG_NAME_RATIO:
                count += 1
    return count


def _has_identity_signal(reasons: list[str]) -> bool:
    for reason in reasons:
        if reason.startswith(("domain_", "geo_identity_")):
            return True
        ratio = _fuzzy_ratio_from_reason(reason)
        if ratio is not None and ratio >= STRONG_NAME_RATIO:
            return True
    return False


def _geo_score(
    distance_m: float | None,
    *,
    allow_identity: bool,
) -> tuple[float, int, list[str]]:
    if distance_m is None:
        return 0.0, 0, []

    rounded = int(round(distance_m))
    if distance_m <= GEO_IDENTITY_METERS:
        if allow_identity:
            return 0.75, 2, [f"distance_{rounded}m", f"geo_identity_{GEO_IDENTITY_METERS}m"]
        return 0.25, 1, [f"distance_{rounded}m"]
    if distance_m <= 50:
        if allow_identity:
            return 0.45, 1, [f"distance_{rounded}m"]
        return 0.20, 0, [f"distance_{rounded}m"]
    if distance_m <= 100:
        if allow_identity:
            return 0.35, 1, [f"distance_{rounded}m"]
        return 0.20, 0, [f"distance_{rounded}m"]
    if distance_m <= NEARBY_METERS:
        if allow_identity:
            return 0.25, 1, [f"distance_{rounded}m"]
        return 0.15, 0, [f"distance_{rounded}m"]
    if distance_m <= GEO_CANDIDATE_METERS:
        if allow_identity:
            return 0.15, 0, [f"distance_{rounded}m"]
        return 0.10, 0, [f"distance_{rounded}m"]
    return 0.0, 0, []


def _allows_geo_identity(record: DiscoveryRecord) -> bool:
    precision = _metadata_value(record, "location_precision")
    if precision in {"approximate", "unknown"}:
        return False

    metadata_confidence = _metadata_value(record, "metadata_confidence")
    if metadata_confidence == "low":
        return False

    record_class = _metadata_value(record, "record_class")
    if record_class in {"defunct", "uncertain", "multi_faith", "other"}:
        return False

    return True


def _metadata_value(record: DiscoveryRecord, key: str) -> str | None:
    value = record.metadata.get(key)
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def distance_meters(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
) -> float | None:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    radius_m = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def mosque_coordinates(mosque: Mosque) -> tuple[float | None, float | None]:
    if mosque.location is None:
        return None, None
    try:
        shape = to_shape(mosque.location)
        if isinstance(shape, Point):
            return shape.y, shape.x
    except Exception:  # noqa: BLE001
        return None, None
    return None, None
