from __future__ import annotations

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import AuthoringTargetKind
from uk_jamaat_directory.ingest.authoring.discovery import (
    ScoredLink,
    _parse_anchors,
    _rank_candidates,
    coerce_kind_from_content_type,
    looks_like_javascript_widget,
)

SAMPLE_HTML = """
<!doctype html>
<html>
  <body>
    <a href="/prayer-times">Prayer Times</a>
    <a href="/donate">Donate Now</a>
    <a href="/news">Latest news</a>
    <a href="https://hujjat.org/calendar/2026">Salat Calendar</a>
    <a href="mailto:foo@bar">Email</a>
  </body>
</html>
"""


def test_parse_anchors_extracts_href_and_text() -> None:
    anchors = _parse_anchors(SAMPLE_HTML)
    pairs = [(href, text) for href, text in anchors]
    assert ("/prayer-times", "Prayer Times") in pairs
    assert ("/donate", "Donate Now") in pairs
    assert ("https://hujjat.org/calendar/2026", "Salat Calendar") in pairs


def test_rank_candidates_picks_prayer_link_over_donate() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://x/y",
        authoring_keyword_boost=2.0,
    )
    anchors = _parse_anchors(SAMPLE_HTML)
    candidates = _rank_candidates(
        anchors,
        base_url="https://hujjat.org/",
        base_domain="hujjat.org",
        settings=settings,
        limit=5,
    )
    urls = [item.url for item in candidates]
    assert urls[0].endswith("/prayer-times")
    assert "/donate" not in urls
    assert "/news" not in urls


def test_rank_candidates_rejects_external_links() -> None:
    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://x/y",
    )
    anchors = [("https://other.example/prayer-times", "Prayer Times")]
    candidates = _rank_candidates(
        anchors,
        base_url="https://hujjat.org/",
        base_domain="hujjat.org",
        settings=settings,
        limit=5,
    )
    assert candidates == []


def test_classify_kind_from_content_type() -> None:
    assert (
        coerce_kind_from_content_type("text/html; charset=utf-8")
        == AuthoringTargetKind.HTML
    )
    assert (
        coerce_kind_from_content_type("application/pdf")
        == AuthoringTargetKind.PDF
    )
    assert (
        coerce_kind_from_content_type("image/png")
        == AuthoringTargetKind.IMAGE
    )
    assert (
        coerce_kind_from_content_type("application/json")
        == AuthoringTargetKind.JSON
    )
    assert (
        coerce_kind_from_content_type("application/octet-stream")
        == AuthoringTargetKind.UNKNOWN
    )


def test_looks_like_javascript_widget_when_text_empty() -> None:
    assert (
        looks_like_javascript_widget(
            sample_text="", sample_html='<html><script src="x.js"></script></html>'
        )
        == AuthoringTargetKind.RENDERED_HTML
    )
    assert (
        looks_like_javascript_widget(
            sample_text="hello", sample_html="<html></html>"
        )
        == AuthoringTargetKind.HTML
    )


def test_scored_link_is_dataclass() -> None:
    link = ScoredLink(url="https://hujjat.org/prayer-times", score=1.0, text="x")
    assert link.url == "https://hujjat.org/prayer-times"
    assert link.matched_keywords == ()
