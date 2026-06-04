from __future__ import annotations

import math

from geoalchemy2.shape import to_shape
from rapidfuzz import fuzz

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
NEARBY_METERS = 150


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

    lat, lon = _mosque_coordinates(mosque)
    distance_m = _distance_meters(record.latitude, record.longitude, lat, lon)
    if distance_m is not None and distance_m <= NEARBY_METERS:
        score += 0.30
        signals += 1
        reasons.append(f"distance_{int(distance_m)}m")

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
    best = ranked[0]

    if len(ranked) > 1 and ranked[1].score >= 0.5 and (best.score - ranked[1].score) < 0.1:
        return DiscoveryMatch(
            decision=MatchDecision.NEEDS_REVIEW,
            score=best.score,
            reasons=["ambiguous_multiple_candidates"],
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
        return DiscoveryMatch(
            decision=MatchDecision.NEEDS_REVIEW,
            score=best.score,
            reasons=["high_score_insufficient_signals", *best.reasons],
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


def _count_strong_signals(reasons: list[str]) -> int:
    count = 0
    for reason in reasons:
        if reason.startswith(("postcode_", "distance_")):
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
        if reason.startswith("domain_"):
            return True
        ratio = _fuzzy_ratio_from_reason(reason)
        if ratio is not None and ratio >= STRONG_NAME_RATIO:
            return True
    return False


def _distance_meters(
    lat1: float | None,
    lon1: float | None,
    lat2: float | None,
    lon2: float | None,
) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    radius_m = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _mosque_coordinates(mosque: Mosque) -> tuple[float | None, float | None]:
    if mosque.location is None:
        return None, None
    try:
        shape = to_shape(mosque.location)
        return shape.y, shape.x
    except Exception:  # noqa: BLE001
        return None, None
