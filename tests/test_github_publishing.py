from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase12_license_and_policy_files_exist() -> None:
    for name in (
        "LICENSE.md",
        "DATA_LICENSE.md",
        "ATTRIBUTION.md",
        "SECURITY.md",
    ):
        assert (ROOT / name).is_file(), name


def test_data_license_references_odbl() -> None:
    text = (ROOT / "DATA_LICENSE.md").read_text()
    assert "ODbL" in text
    assert "private_use_only" in text or "public_redistribution_allowed" in text


def test_license_marks_code_proprietary() -> None:
    text = (ROOT / "LICENSE.md").read_text()
    assert "proprietary" in text.lower() or "All rights reserved" in text


def test_dependabot_config_present() -> None:
    text = (ROOT / ".github" / "dependabot.yml").read_text()
    assert "package-ecosystem: pip" in text
    assert "package-ecosystem: github-actions" in text


def test_dependency_review_workflow_present() -> None:
    text = (ROOT / ".github" / "workflows" / "dependency-review.yml").read_text()
    assert "dependency-review-action" in text
    assert "pull_request:" in text
