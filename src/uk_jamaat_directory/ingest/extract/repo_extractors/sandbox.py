from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    ExtractContext,
    ExtractorArtifact,
)
from uk_jamaat_directory.ingest.extract.repo_extractors.registry import (
    RegisteredExtractor,
    load_all_extractors,
)


def _build_context(payload: dict[str, Any]) -> tuple[RegisteredExtractor, ExtractContext]:
    extractor_key = payload["extractor_key"]
    matches = [r for r in load_all_extractors() if r.extractor.key == extractor_key]
    if not matches:
        msg = f"extractor not found: {extractor_key}"
        raise SystemExit(msg)
    if len(matches) > 1:
        msg = f"multiple extractors registered for key: {extractor_key}"
        raise SystemExit(msg)
    registered = matches[0]

    artifacts = {
        name: ExtractorArtifact(
            target_label=body["target_label"],
            target_url=body["target_url"],
            content_type=body.get("content_type"),
            body=bytes.fromhex(body["body_hex"]),
            content_hash=body.get("content_hash"),
        )
        for name, body in payload.get("artifacts", {}).items()
    }

    context = ExtractContext(
        source_id=payload.get("source_id", ""),
        mosque_name=payload.get("mosque_name", ""),
        mosque_id=payload.get("mosque_id"),
        source_url=payload.get("source_url", ""),
        timezone=payload.get("timezone", "Europe/London"),
        artifacts=artifacts,
        extra=payload.get("extra", {}),
    )
    return registered, context


def _block_network() -> None:
    import socket

    def _denied(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("network access is not allowed in repo extractor sandbox")

    socket.socket = _denied  # type: ignore[assignment]
    socket.create_connection = _denied  # type: ignore[assignment]
    socket.getaddrinfo = _denied  # type: ignore[assignment]


def _emit(result: Any) -> None:
    if hasattr(result, "model_dump"):
        sys.stdout.write(json.dumps(result.model_dump(mode="json")))
    else:
        sys.stdout.write(json.dumps(result))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repo_extractor_sandbox")
    parser.add_argument("--input", required=True, help="Path to input JSON file")
    parser.add_argument("--output", required=True, help="Path to output JSON file")
    args = parser.parse_args(argv)

    _block_network()

    with open(args.input, encoding="utf-8") as handle:
        payload = json.load(handle)

    registered, context = _build_context(payload)
    extractor = registered.extractor
    result = extractor.extract(context)
    output_path = args.output
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(result.model_dump_json())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
