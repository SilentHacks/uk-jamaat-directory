from __future__ import annotations

import pytest

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
    ExtractContext,
    ExtractorEvidence,
    ExtractorResult,
    ExtractorRow,
    RefreshPolicy,
    RunFrequency,
    SourceMatch,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.registry import (
    find_extractor_for_source,
    load_all_extractors,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.validator import (
    check_capabilities,
    check_extractor,
    check_extractor_result,
    check_script_source,
    check_target_url,
    validate_refresh_policy,
    validate_source_match,
)


class TestRegistry:
    def test_load_all_extractors_includes_synthetic(self) -> None:
        keys = {entry.extractor.key for entry in load_all_extractors()}
        assert "synthetic_html_table" in keys

    def test_find_extractor_for_source_by_domain(self) -> None:
        matches = find_extractor_for_source(domain="synthetic.example", mosque_name=None)
        keys = [m.extractor.key for m in matches]
        assert "synthetic_html_table" in keys

    def test_find_extractor_for_source_no_match(self) -> None:
        matches = find_extractor_for_source(domain="other.example", mosque_name="Synthetic Masjid")
        assert all(m.extractor.key != "synthetic_html_table" for m in matches)


class TestStaticGates:
    def test_clean_script_passes(self) -> None:
        source = (
            "from uk_jamaat_directory.ingest.extract.repo_extractors.contract"
            " import BaseMosqueWebsiteExtractor, ExtractContext, ExtractorResult\n"
            "class Extractor(BaseMosqueWebsiteExtractor):\n"
            "    key='k'\n"
            "    version='1'\n"
            "    refresh_policy=RefreshPolicy(frequency=RunFrequency.DAILY)\n"
            "    targets=()\n"
            "    def extract(self, ctx):\n"
            "        return ExtractorResult()\n"
        )
        result = check_script_source(source)
        assert result.ok

    def test_banned_import_subprocess(self) -> None:
        source = "import subprocess\n"
        result = check_script_source(source)
        assert not result.ok
        assert any("subprocess" in issue for issue in result.issues)

    def test_banned_import_socket(self) -> None:
        source = "import socket\n"
        result = check_script_source(source)
        assert not result.ok

    def test_banned_from_import(self) -> None:
        source = "from urllib.request import urlopen\n"
        result = check_script_source(source)
        assert not result.ok

    def test_banned_eval_call(self) -> None:
        source = "x = eval('1')\n"
        result = check_script_source(source)
        assert not result.ok

    def test_unknown_module_rejected(self) -> None:
        source = "import requests\n"
        result = check_script_source(source)
        assert not result.ok

    def test_synthetic_script_passes(self) -> None:
        from pathlib import Path

        source = Path(
            "src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts/synthetic_html_table.py"
        ).read_text()
        result = check_script_source(source)
        assert result.ok, result.issues


class TestCapabilityAndTargetGates:
    def test_target_url_must_be_same_domain(self) -> None:
        issue = check_target_url("https://other.example/page", allowed_domain="mosque.example")
        assert issue is not None
        assert "outside allowed domain" in issue

    def test_target_url_accepts_subdomain(self) -> None:
        issue = check_target_url("https://www.mosque.example/page", allowed_domain="mosque.example")
        assert issue is None

    def test_check_extractor_flags_no_targets(self) -> None:
        entry = load_all_extractors()[0]
        # Mutate to remove targets for the check.
        original = entry.extractor.targets
        try:
            entry.extractor.targets = ()
            issues = check_extractor(entry.extractor, allowed_domain="synthetic.example")
            assert any("no targets" in i for i in issues)
        finally:
            entry.extractor.targets = original

    def test_check_capabilities_unknown_kind(self) -> None:
        from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
            TargetSpec as _TargetSpec,
        )

        target = _TargetSpec.model_construct(
            label="x",
            url="https://x.example/p",
            kind="bogus",
            path=None,
            requires_javascript=False,
            requires_pdf=False,
            requires_ocr=False,
        )

        class FakeExtractor(BaseMosqueWebsiteExtractor):
            key = "k"
            version = "1"
            refresh_policy = RefreshPolicy(frequency=RunFrequency.DAILY)
            targets = (target,)

            def extract(self, ctx: ExtractContext) -> ExtractorResult:
                return ExtractorResult(no_schedule_reason="n/a")

        issues = check_capabilities(FakeExtractor())
        assert any("unknown target kind" in i for i in issues)


class TestOutputContract:
    def test_empty_rows_requires_reason(self) -> None:
        with pytest.raises(ValueError):
            ExtractorResult(rows=[])

    def test_valid_result_passes(self) -> None:
        result = ExtractorResult(
            no_schedule_reason="n/a",
        )
        issues = check_extractor_result(result)
        assert not issues

    def test_duplicate_rows_flagged(self) -> None:
        from datetime import date

        from uk_jamaat_directory.domain import Prayer

        ev = ExtractorEvidence(
            target_label="t",
            target_url="https://x.example",
            extractor_key="k",
            extractor_version="1",
        )
        row = ExtractorRow(
            date=date(2026, 6, 8),
            prayer=Prayer.FAJR,
            jamaat_time=__import__("datetime").time(4, 0),
            evidence=ev,
        )
        result = ExtractorResult(rows=[row, row], no_schedule_reason="ok")
        issues = check_extractor_result(result)
        assert any("duplicate" in i for i in issues)


class TestSourceMatchAndPolicy:
    def test_invalid_domain_format(self) -> None:
        match = SourceMatch(domains=("not a domain!",))
        assert validate_source_match(match)  # non-empty issues

    def test_valid_frequency(self) -> None:
        policy = RefreshPolicy(frequency=RunFrequency.DAILY)
        assert not validate_refresh_policy(policy)
