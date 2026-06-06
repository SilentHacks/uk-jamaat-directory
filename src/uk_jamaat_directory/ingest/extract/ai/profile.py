from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExtractionProfile(BaseModel):
    """Structured output from AI reconnaissance of a mosque website."""

    profile_version: str = "1.0"
    timetable_url: str | None = None
    asset_type: Literal["html_table", "html_list", "pdf", "image", "json_feed", "unknown"] = (
        "unknown"
    )
    extraction_strategy: Literal[
        "css_selector",
        "llm_structured",
        "pdf_parser",
        "ocr",
        "api_endpoint",
        "unknown",
    ] = "unknown"
    css_selector: str | None = None
    date_range_hint: dict[str, str] | None = None
    requires_javascript: bool = False
    requires_pdf_parsing: bool = False
    requires_ocr: bool = False
    prayers_observed: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    review_notes: str = ""
