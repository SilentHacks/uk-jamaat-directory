from __future__ import annotations

import pytest
from pydantic import ValidationError

from uk_jamaat_directory.ingest.extract.ai.profile import ExtractionProfile


class TestExtractionProfile:
    def test_valid_profile(self):
        profile = ExtractionProfile(
            timetable_url="/prayer-times",
            asset_type="html_table",
            extraction_strategy="css_selector",
            css_selector=".prayer-times",
            confidence=0.92,
            review_notes="Clear table",
        )
        assert profile.timetable_url == "/prayer-times"
        assert profile.confidence == 0.92

    def test_confidence_out_of_range_high(self):
        with pytest.raises(ValidationError):
            ExtractionProfile(confidence=1.5)

    def test_confidence_out_of_range_low(self):
        with pytest.raises(ValidationError):
            ExtractionProfile(confidence=-0.1)

    def test_invalid_asset_type(self):
        with pytest.raises(ValidationError):
            ExtractionProfile(asset_type="invalid_type")

    def test_invalid_extraction_strategy(self):
        with pytest.raises(ValidationError):
            ExtractionProfile(extraction_strategy="invalid_strategy")

    def test_defaults(self):
        profile = ExtractionProfile()
        assert profile.asset_type == "unknown"
        assert profile.extraction_strategy == "unknown"
        assert profile.confidence == 0.0
        assert profile.requires_javascript is False
        assert profile.prayers_observed == []

    def test_serialization(self):
        profile = ExtractionProfile(
            timetable_url="/times",
            asset_type="html_list",
            confidence=0.85,
        )
        data = profile.model_dump(mode="json")
        assert data["timetable_url"] == "/times"
        assert data["asset_type"] == "html_list"
        assert data["confidence"] == 0.85
