from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from uk_jamaat_directory.ingest.extract.ai.profile import ExtractionProfile


@dataclass
class AgentResult:
    """Parsed result from an autonomous agent profiling run."""

    profile: ExtractionProfile
    raw_json: dict | None = None
    parse_errors: list[str] = field(default_factory=list)


def parse_agent_result(path: Path) -> AgentResult | None:
    """Read and validate the JSON artifact written by an agent.

    Returns ``None`` if the file is missing or unreadable.
    Returns an ``AgentResult`` with parse errors if the JSON is malformed
    or fails schema validation.
    """
    if not path.exists():
        return None

    raw_text = path.read_text(encoding="utf-8")
    if not raw_text.strip():
        return None

    try:
        raw_json = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return AgentResult(
            profile=ExtractionProfile(
                review_notes=f"Agent result was not valid JSON: {exc}"
            ),
            parse_errors=[f"JSON decode error: {exc}"],
        )

    if not isinstance(raw_json, dict):
        return AgentResult(
            profile=ExtractionProfile(
                review_notes="Agent result was not a JSON object"
            ),
            parse_errors=["Top-level JSON value is not an object"],
        )

    # Translate agent-specific keys to ExtractionProfile fields
    data: dict = {
        "timetable_url": raw_json.get("timetable_url"),
        "asset_type": raw_json.get("asset_type", "unknown"),
        "extraction_strategy": raw_json.get("extraction_strategy", "unknown"),
        "css_selector": raw_json.get("css_selector"),
        "confidence": raw_json.get("confidence", 0.0),
        "review_notes": raw_json.get("review_notes", ""),
        "found": raw_json.get("found", False),
        "urls_explored": raw_json.get("urls_explored", []),
        "pages_fetched": raw_json.get("pages_fetched", 0),
        "navigation_log": raw_json.get("navigation_log", ""),
    }

    try:
        profile = ExtractionProfile.model_validate(data)
    except Exception as exc:
        return AgentResult(
            profile=ExtractionProfile(
                review_notes=f"Profile validation failed: {exc}; raw: {json.dumps(raw_json)[:500]}"
            ),
            raw_json=raw_json,
            parse_errors=[f"Profile validation error: {exc}"],
        )

    return AgentResult(profile=profile, raw_json=raw_json)
