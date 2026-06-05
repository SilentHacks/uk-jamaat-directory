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
