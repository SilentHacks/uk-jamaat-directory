from __future__ import annotations

import uuid

from geoalchemy2 import WKTElement

from uk_jamaat_directory.domain import SourceType
from uk_jamaat_directory.ingest.discovery.matching import decide_match, score_mosque_candidate
from uk_jamaat_directory.ingest.discovery.records import (
    DiscoveryRecord,
    MatchDecision,
    ScoredMosqueCandidate,
)
from uk_jamaat_directory.models.core import Mosque


def _mosque(**kwargs) -> Mosque:
    defaults = {
        "id": uuid.uuid4(),
        "name": "Central Masjid",
        "normalized_name": "central masjid",
        "postcode": "E2 1AA",
        "city": "London",
        "website_url": "https://central.example.org",
    }
    defaults.update(kwargs)
    return Mosque(**defaults)


def test_auto_link_requires_multiple_signals() -> None:
    record = DiscoveryRecord(
        source_type=SourceType.OPENSTREETMAP,
        external_id="node/1",
        name="Central Masjid",
        postcode="E2 1AA",
        city="London",
        website_url="https://central.example.org",
        latitude=51.53,
        longitude=-0.07,
    )
    scored = score_mosque_candidate(record, _mosque())
    assert scored is not None
    match = decide_match(record, [scored])
    assert match.decision == MatchDecision.AUTO_LINK


def test_name_only_match_is_not_auto_linked() -> None:
    record = DiscoveryRecord(
        source_type=SourceType.MYLOCALMASJID,
        external_id="mlm-9",
        name="Central Masjid",
        city="London",
    )
    scored = score_mosque_candidate(
        record,
        _mosque(postcode="M1 1AE", website_url=None),
    )
    assert scored is not None
    match = decide_match(record, [scored])
    assert match.decision in {MatchDecision.NEEDS_REVIEW, MatchDecision.CREATE_NEEDS_REVIEW}


def test_very_close_geo_only_unique_match_can_auto_link() -> None:
    record = DiscoveryRecord(
        source_type=SourceType.OPENSTREETMAP,
        external_id="node/99",
        name="Riverside Community Centre",
        postcode="E2 1AA",
        city="London",
        latitude=51.5308,
        longitude=-0.0714,
    )
    scored = score_mosque_candidate(
        record,
        _mosque(
            name="Central Masjid",
            normalized_name="central masjid",
            postcode="E2 9ZZ",
            website_url=None,
            location=WKTElement("POINT(-0.0714 51.5308)", srid=4326),
        ),
    )
    assert scored is not None
    assert scored.score >= 0.75
    assert "geo_identity_25m" in scored.reasons
    match = decide_match(record, [scored])
    assert match.decision == MatchDecision.AUTO_LINK


def test_approximate_uncertain_geo_only_match_needs_review() -> None:
    record = DiscoveryRecord(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-uncertain",
        name="Riverside Community Hall",
        postcode="E2 1AA",
        city="London",
        latitude=51.5308,
        longitude=-0.0714,
        metadata={
            "record_class": "uncertain",
            "location_precision": "approximate",
            "metadata_confidence": "low",
        },
    )
    scored = score_mosque_candidate(
        record,
        _mosque(
            name="Central Masjid",
            normalized_name="central masjid",
            website_url=None,
            location=WKTElement("POINT(-0.0714 51.5308)", srid=4326),
        ),
    )
    assert scored is not None
    assert "geo_identity_25m" not in scored.reasons
    match = decide_match(record, [scored])
    assert match.decision == MatchDecision.NEEDS_REVIEW


def test_nearby_geo_with_postcode_match_needs_review_when_name_differs() -> None:
    record = DiscoveryRecord(
        source_type=SourceType.OPENSTREETMAP,
        external_id="node/100",
        name="Riverside Community Centre",
        postcode="E2 1AA",
        city="London",
        latitude=51.5308,
        longitude=-0.0714,
    )
    scored = score_mosque_candidate(
        record,
        _mosque(
            name="Central Masjid",
            normalized_name="central masjid",
            website_url=None,
            location=WKTElement("POINT(-0.0708 51.5308)", srid=4326),
        ),
    )
    assert scored is not None
    assert 0.75 <= scored.score < 1.0
    match = decide_match(record, [scored])
    assert match.decision == MatchDecision.NEEDS_REVIEW
    assert "high_score_insufficient_signals" in match.reasons[0]


def test_ambiguous_candidates_need_review() -> None:
    record = DiscoveryRecord(
        source_type=SourceType.OPENSTREETMAP,
        external_id="node/2",
        name="Central Masjid",
        postcode="E2 1AA",
    )
    first = ScoredMosqueCandidate(mosque_id=uuid.uuid4(), score=0.8, reasons=["postcode_match"])
    second = ScoredMosqueCandidate(mosque_id=uuid.uuid4(), score=0.78, reasons=["postcode_match"])
    match = decide_match(record, [first, second])
    assert match.decision == MatchDecision.NEEDS_REVIEW


def test_name_evidence_override_promotes_name_match_candidate() -> None:
    """Top candidate has only postcode+geo; second has partial name match.

    The matcher should prefer the name-matching candidate and surface the
    override as a review reason. The result is needs-review (not auto-link)
    with the promoted candidate as the top alternative.
    """
    record = DiscoveryRecord(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-801",
        name="Madrassa Al Arabia Al Islamia",
    )
    name_match = ScoredMosqueCandidate(
        mosque_id=uuid.uuid4(),
        score=0.60,
        reasons=["name_ratio_86", "distance_87m", "signals_1"],
    )
    postcode_only = ScoredMosqueCandidate(
        mosque_id=uuid.uuid4(),
        score=0.80,
        reasons=["postcode_match", "distance_33m", "signals_2"],
    )
    match = decide_match(record, [postcode_only, name_match])
    assert match.decision == MatchDecision.NEEDS_REVIEW
    assert match.alternatives, "expected alternatives to surface the promoted candidate"
    assert match.alternatives[0].mosque_id == name_match.mosque_id
    assert "name_evidence_override" in match.reasons


def test_name_evidence_override_does_not_apply_when_top_has_name_evidence() -> None:
    record = DiscoveryRecord(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-1",
        name="Central Masjid",
    )
    named_top = ScoredMosqueCandidate(
        mosque_id=uuid.uuid4(),
        score=0.90,
        reasons=["name_ratio_95", "domain_match", "signals_2"],
    )
    unnamed_close = ScoredMosqueCandidate(
        mosque_id=uuid.uuid4(),
        score=0.78,
        reasons=["postcode_match", "distance_50m", "signals_2"],
    )
    match = decide_match(record, [named_top, unnamed_close])
    assert "name_evidence_override" not in match.reasons
    assert match.decision == MatchDecision.AUTO_LINK
    assert match.mosque_id == named_top.mosque_id


def test_name_evidence_override_respects_score_gap() -> None:
    """The name-matching candidate is too far below the top to override."""
    record = DiscoveryRecord(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-2",
        name="Central Masjid",
    )
    far_off_name_match = ScoredMosqueCandidate(
        mosque_id=uuid.uuid4(),
        score=0.40,
        reasons=["name_ratio_86", "distance_300m", "signals_1"],
    )
    very_close = ScoredMosqueCandidate(
        mosque_id=uuid.uuid4(),
        score=0.95,
        reasons=["postcode_match", "geo_identity_25m", "signals_2"],
    )
    match = decide_match(record, [very_close, far_off_name_match])
    assert "name_evidence_override" not in match.reasons
    assert match.mosque_id == very_close.mosque_id
    assert match.decision == MatchDecision.AUTO_LINK


def test_parent_org_source_penalised_when_no_name_match() -> None:
    """A parent-organisation source (Welfare Association etc.) sharing a
    building with a real mosque should be flagged and its score reduced.
    Without the penalty, the source would auto-link to a venue 30 m away
    on postcode + geo evidence alone; with the penalty, it lands in
    review with a `parent_org_source` reason for the operator to reject."""
    record = DiscoveryRecord(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-welfare",
        name="Islamic Cultural Welfare Association",
        postcode="E2 1AA",
        city="London",
        latitude=51.5308,
        longitude=-0.0714,
    )
    scored = score_mosque_candidate(
        record,
        _mosque(
            name="Jame Masjid",
            normalized_name="jame masjid",
            location=WKTElement("POINT(-0.0708 51.5308)", srid=4326),
        ),
    )
    assert scored is not None
    assert "parent_org_source" in scored.reasons
    match = decide_match(record, [scored])
    assert match.decision == MatchDecision.NEEDS_REVIEW


def test_parent_org_source_unaffected_when_name_matches() -> None:
    """If the parent-org source actually name-matches a candidate, the
    penalty is not applied."""
    record = DiscoveryRecord(
        source_type=SourceType.MUSLIMSINBRITAIN,
        external_id="mib-welfare-2",
        name="Falah Education Society",
        postcode="E2 1AA",
        city="London",
        latitude=51.53,
        longitude=-0.07,
    )
    scored = score_mosque_candidate(
        record,
        _mosque(
            name="Falah Education Society Centre",
            normalized_name="falah education society centre",
            location=WKTElement("POINT(-0.07 51.53)", srid=4326),
        ),
    )
    assert scored is not None
    assert "parent_org_source" not in scored.reasons
