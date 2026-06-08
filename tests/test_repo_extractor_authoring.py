from __future__ import annotations

from uk_jamaat_directory.ingest.extract.repo_extractors.authoring_prompt import (
    build_authoring_prompt,
)


class TestAuthoringPrompt:
    def test_includes_extractor_key_and_url(self) -> None:
        prompt = build_authoring_prompt(
            source_id="src-123",
            mosque_name="Example Masjid",
            website_url="https://example.org/prayer-times",
            extractor_key="example_org",
            max_pages=10,
        )
        assert "example_org" in prompt
        assert "Example Masjid" in prompt
        assert "https://example.org/prayer-times" in prompt
        assert "validate-repo-extractor" in prompt
        assert "Relative" in prompt or "relative" in prompt

    def test_lists_supported_frequencies(self) -> None:
        prompt = build_authoring_prompt(
            source_id="src-1",
            mosque_name="Test",
            website_url="https://test.example",
            extractor_key="test",
            max_pages=5,
        )
        assert "hourly" in prompt
        assert "daily" in prompt
        assert "monthly" in prompt
