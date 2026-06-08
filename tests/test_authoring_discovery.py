from __future__ import annotations

from uk_jamaat_directory.config import Settings
from uk_jamaat_directory.domain import AuthoringTargetKind
from uk_jamaat_directory.ingest.authoring.discovery import (
    coerce_kind_from_content_type,
    looks_like_javascript_widget,
)


def test_classify_kind_from_content_type() -> None:
    assert coerce_kind_from_content_type("text/html; charset=utf-8") == AuthoringTargetKind.HTML
    assert coerce_kind_from_content_type("application/pdf") == AuthoringTargetKind.PDF
    assert coerce_kind_from_content_type("image/png") == AuthoringTargetKind.IMAGE
    assert coerce_kind_from_content_type("application/json") == AuthoringTargetKind.JSON
    assert coerce_kind_from_content_type("application/octet-stream") == AuthoringTargetKind.UNKNOWN


def test_looks_like_javascript_widget_when_text_empty() -> None:
    assert (
        looks_like_javascript_widget(
            content_type="text/html",
            body=b'<html><script src="x.js"></script></html>',
        )
        is True
    )
    assert (
        looks_like_javascript_widget(
            content_type="text/html",
            body=b"<html><body>hello world</body></html>",
        )
        is False
    )
    assert (
        looks_like_javascript_widget(
            content_type="application/pdf",
            body=b"%PDF-1.4\n",
        )
        is False
    )
    assert (
        looks_like_javascript_widget(
            content_type="text/html",
            body=b"",
        )
        is True
    )


def test_classify_kind_handles_blank_content_type() -> None:
    assert coerce_kind_from_content_type("") == AuthoringTargetKind.UNKNOWN
    assert coerce_kind_from_content_type(None) == AuthoringTargetKind.UNKNOWN


def test_settings_authoring_concurrency_default() -> None:
    settings = Settings(environment="test", database_url="postgresql+asyncpg://x/y")
    assert settings.authoring_concurrency >= 1
    assert settings.authoring_per_source_timeout_seconds > 0
