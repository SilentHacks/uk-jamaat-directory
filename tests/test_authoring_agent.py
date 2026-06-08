from __future__ import annotations

from uk_jamaat_directory.domain import AuthoringTargetKind
from uk_jamaat_directory.ingest.authoring.agent import parse_agent_report


def test_parse_status_only() -> None:
    report = parse_agent_report("STATUS=authored")
    assert report.status == "authored"
    assert report.target_url is None


def test_parse_full_authored_block() -> None:
    text = (
        "Some prose from the agent.\n"
        "I navigated to the timetable page.\n"
        "STATUS=authored\n"
        "TARGET_URL=https://hujjat.org/prayer-times\n"
        "TARGET_KIND=html\n"
        "SCRIPT_PATH=src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts/hujjat.py\n"
    )
    report = parse_agent_report(text)
    assert report.status == "authored"
    assert report.target_url == "https://hujjat.org/prayer-times"
    assert report.target_kind == AuthoringTargetKind.HTML
    assert (
        report.script_path
        == "src/uk_jamaat_directory/ingest/extract/repo_extractors/scripts/hujjat.py"
    )


def test_parse_skipped_review_with_reason() -> None:
    text = (
        "STATUS=skipped_review\n"
        "TARGET_URL=https://hujjat.org/calendar.pdf\n"
        "TARGET_KIND=pdf\n"
        "REASON=pdf target — ocr not yet implemented\n"
    )
    report = parse_agent_report(text)
    assert report.status == "skipped_review"
    assert report.target_kind == AuthoringTargetKind.PDF
    assert "ocr" in (report.reason or "")


def test_parse_block_inside_code_fence() -> None:
    text = (
        "Here is my report:\n"
        "```\n"
        "STATUS=authored\n"
        "TARGET_KIND=html\n"
        "```\n"
    )
    report = parse_agent_report(text)
    assert report.status == "authored"
    assert report.target_kind == AuthoringTargetKind.HTML


def test_parse_block_with_leading_garbage() -> None:
    text = (
        "I went to the site and found the timetable at /prayer-times.\n"
        "It is a PDF, so I will skip authoring.\n"
        "\n"
        "STATUS=skipped_review\n"
        "TARGET_URL=https://hujjat.org/prayer-times.pdf\n"
        "TARGET_KIND=pdf\n"
        "REASON=pdf target — ocr not yet implemented\n"
    )
    report = parse_agent_report(text)
    assert report.status == "skipped_review"
    assert report.target_kind == AuthoringTargetKind.PDF


def test_parse_handles_unknown_kind() -> None:
    report = parse_agent_report("STATUS=skipped_review\nTARGET_KIND=mystery\n")
    assert report.target_kind == AuthoringTargetKind.UNKNOWN


def test_parse_handles_blank_input() -> None:
    report = parse_agent_report("")
    assert report.status is None


def test_parse_ignores_unknown_keys() -> None:
    report = parse_agent_report(
        "STATUS=authored\nFOO=bar\nTARGET_KIND=html\n"
    )
    assert report.status == "authored"
    assert report.target_kind == AuthoringTargetKind.HTML
