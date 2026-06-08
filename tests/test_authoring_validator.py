from __future__ import annotations

from pathlib import Path

import pytest

from uk_jamaat_directory.domain import (
    AuthoringTargetKind,
)
from uk_jamaat_directory.ingest.authoring.validator_post import (
    validate_draft_source,
    validate_extractor_for_domain,
    write_draft_to_scripts,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.scripts.synthetic_html_table import (
    Extractor,
)


def test_validate_draft_source_passes_synthetic() -> None:
    module = (
        "from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (\n"
        "    BaseMosqueWebsiteExtractor,\n"
        "    ExtractContext,\n"
        "    ExtractorResult,\n"
        ")\n"
        "class Extractor(BaseMosqueWebsiteExtractor):\n"
        "    key = 'synthetic_html_table'\n"
        "    version = '2026.06.08.1'\n"
        "    def extract(self, ctx: ExtractContext) -> ExtractorResult:\n"
        "        return ExtractorResult(rows=[], no_schedule_reason='empty')\n"
    )
    issues = validate_draft_source(module)
    assert issues == []


def test_validate_draft_source_flags_banned_import() -> None:
    bad = (
        "import os\n"
        "from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (\n"
        "    BaseMosqueWebsiteExtractor,\n"
        ")\n"
        "class Extractor(BaseMosqueWebsiteExtractor):\n"
        "    key = 'x'\n"
        "    version = '2026.06.08.1'\n"
        "    def extract(self, ctx):\n"
        "        pass\n"
    )
    issues = validate_draft_source(bad)
    assert any("os" in issue for issue in issues)


def test_validate_extractor_for_domain_synthetic() -> None:
    extractor = Extractor()
    issues = validate_extractor_for_domain(extractor=extractor, allowed_domain="synthetic.example")
    assert issues == []


def test_validate_extractor_for_domain_rejects_other_domain() -> None:
    extractor = Extractor()
    issues = validate_extractor_for_domain(extractor=extractor, allowed_domain="other.example")
    assert any("outside allowed domain" in issue for issue in issues)


def test_write_draft_to_scripts_creates_file(tmp_path: Path) -> None:
    out = write_draft_to_scripts(
        extractor_key="My Extractor v2",  # type: ignore[arg-type]
        source="print('hi')\n",
        scripts_dir=str(tmp_path),
    )
    assert out == str(tmp_path / "my_extractor_v2.py")
    assert Path(out).read_text(encoding="utf-8") == "print('hi')\n"


def test_write_draft_to_scripts_rejects_empty_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_draft_to_scripts(extractor_key="!!!", source="x", scripts_dir=str(tmp_path))


def test_target_kind_enum_values() -> None:
    assert AuthoringTargetKind.PDF.value == "pdf"
    assert AuthoringTargetKind.HTML.value == "html"
    assert AuthoringTargetKind.RENDERED_HTML.value == "rendered_html"
    assert AuthoringTargetKind.UNKNOWN.value == "unknown"
