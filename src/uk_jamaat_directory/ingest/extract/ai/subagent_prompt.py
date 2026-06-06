from __future__ import annotations

from uk_jamaat_directory.ingest.extract.ai.fetch_bounded import BoundedPageResult


def build_subagent_prompt(
    mosque_name: str,
    city: str | None,
    postcode: str | None,
    source_url: str,
    pages: list[BoundedPageResult],
) -> str:
    """Build a self-contained prompt for a subagent to analyze mosque websites.

    The prompt includes mosque identity details, stripped HTML page snippets,
    and the exact JSON schema expected as output.  Subagents must return ONLY
    valid JSON — no markdown, no explanations.
    """
    parts = [
        "You are a reconnaissance assistant for UK mosque websites. "
        "Inspect the following page snippets and return a strict JSON profile "
        "describing where the prayer timetable lives and how to extract it.\n",
        f"Mosque: {mosque_name}",
    ]
    if city:
        parts.append(f"City: {city}")
    if postcode:
        parts.append(f"Postcode: {postcode}")
    parts.append(f"Source URL: {source_url}")
    parts.append("")

    for page in pages:
        parts.append(f"--- Page: {page.url} ---")
        parts.append(page.body_snippet)
        parts.append("")

    parts.append(
        "Return ONLY a single JSON object matching this exact schema. "
        "Do not include markdown code blocks (```), explanation text, "
        "or any content outside the JSON object.\n"
    )
    parts.append("{")
    parts.append('  "timetable_url": "string or null — direct URL to the timetable page/asset",')
    parts.append(
        '  "asset_type": "html_table" | "html_list" | "pdf" | "image" | "json_feed" | "unknown",'
    )
    parts.append(
        '  "extraction_strategy": '
        '"css_selector" | "llm_structured" | "pdf_parser" | "ocr" | "api_endpoint" | "unknown",'
    )
    parts.append('  "css_selector": "string or null — CSS selector if visible",')
    parts.append(
        '  "date_range_hint": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} or null,'
    )
    parts.append("  \"requires_javascript\": true | false,")
    parts.append("  \"requires_pdf_parsing\": true | false,")
    parts.append("  \"requires_ocr\": true | false,")
    parts.append(
        '  "prayers_observed": ["FAJR", "DHUHR", "ASR", "MAGHRIB", "ISHA", "JUMUAH"],'
    )
    parts.append("  \"confidence\": 0.0 to 1.0 — how sure you are about the timetable location,")
    parts.append(
        '"review_notes": "string — explain your reasoning,'
        ' especially if low confidence"'
    )
    parts.append("}")

    return "\n".join(parts)
