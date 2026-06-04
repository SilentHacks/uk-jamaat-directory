from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from uk_jamaat_directory import __version__
from uk_jamaat_directory.config import Environment, Settings, get_settings
from uk_jamaat_directory.db.session import SessionLocal, create_engine
from uk_jamaat_directory.ingest.policy import parse_publication_policy
from uk_jamaat_directory.ingest.sources.mylocalmasjid import (
    build_coverage_report,
    import_mylocalmasjid_bundle,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid.adapter import ImportFormat, parse_file
from uk_jamaat_directory.services.export_contracts import export_json_schemas, export_openapi


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uk-jamaat-directory",
        description="Operational CLI for the UK Jamaat Directory.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=False)

    export_parser = subparsers.add_parser(
        "export-contracts",
        help="Write OpenAPI and public JSON schemas to docs/api/",
    )
    export_parser.add_argument(
        "--output-dir",
        default="docs/api",
        help="Directory for exported contract files",
    )

    import_mlm = subparsers.add_parser(
        "import-mlm",
        help="Import a MyLocalMasjid JSON/NDJSON/CSV export into private sources and candidates",
    )
    import_mlm.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to export file (synthetic fixtures for local testing)",
    )
    import_mlm.add_argument(
        "--format",
        choices=[item.value for item in ImportFormat],
        default=None,
        help="Override detected file format",
    )
    import_mlm.add_argument(
        "--publication-policy",
        default=None,
        help=(
            "Source publication policy for imported rows "
            "(public_redistribution_allowed, private_use_only, unknown, blocked). "
            "Defaults to UK_JAMAAT_MYLOCALMASJID_PUBLICATION_POLICY or 'unknown'."
        ),
    )
    import_mlm.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the file without writing to the database",
    )

    report_mlm = subparsers.add_parser(
        "report-mlm",
        help="Summarize MyLocalMasjid source coverage, staleness, and open corrections",
    )
    report_mlm.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human summary",
    )

    return parser


def _resolve_mlm_policy(args: argparse.Namespace, settings: Settings):
    raw = args.publication_policy or settings.mylocalmasjid_publication_policy
    return parse_publication_policy(raw)


async def _run_import_mlm(args: argparse.Namespace, settings: Settings) -> int:
    format_hint = ImportFormat(args.format) if args.format else None
    bundle = parse_file(args.input, format_hint=format_hint)
    raw_payload = args.input.read_bytes()
    policy = _resolve_mlm_policy(args, settings)
    fetched_url = f"file://{args.input.resolve()}"

    if args.dry_run:
        schedule_rows = sum(len(mosque.schedules) for mosque in bundle.mosques)
        print(
            f"Dry run OK: {len(bundle.mosques)} mosques, {schedule_rows} schedule rows, "
            f"policy={policy.value}"
        )
        return 0

    create_engine(settings)
    async with SessionLocal() as session:
        result = await import_mylocalmasjid_bundle(
            session,
            bundle,
            raw_payload=raw_payload,
            fetched_url=fetched_url,
            publication_policy=policy,
        )
        await session.commit()

    print(
        "Import complete: "
        f"{result.mosques_upserted} mosques, "
        f"{result.sources_upserted} sources, "
        f"{result.artifacts_created} artifacts, "
        f"{result.candidates_created} candidates "
        f"({result.candidates_skipped} skipped)"
    )
    if result.errors:
        print("Errors:", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    return 0


async def _run_report_mlm(args: argparse.Namespace, settings: Settings) -> int:
    create_engine(settings)
    async with SessionLocal() as session:
        report = await build_coverage_report(session)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    print(f"MyLocalMasjid coverage report ({report.generated_at.isoformat()})")
    print(f"  Sources: {report.source_count} ({report.linked_mosque_count} linked to mosques)")
    print(
        f"  Candidates: pending={report.pending_candidates}, "
        f"approved={report.approved_candidates}"
    )
    print(f"  Publication policies: {report.policy_counts or '(none)'}")
    print(f"  Stale sources (>{STALE_LABEL}): {len(report.stale_sources)}")
    if report.stale_sources:
        for external_id in report.stale_sources[:10]:
            print(f"    - {external_id}")
        if len(report.stale_sources) > 10:
            print(f"    ... and {len(report.stale_sources) - 10} more")
    print(f"  Missing recent schedules: {len(report.sources_missing_recent_schedules)}")
    print(f"  Open corrections (MLM-linked mosques): {report.open_corrections}")
    return 0


STALE_LABEL = "7 days"


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "export-contracts":
        output_dir = Path(args.output_dir)
        openapi_path = export_openapi(output_dir)
        schema_paths = export_json_schemas(output_dir)
        print(f"Wrote {openapi_path}")
        for path in schema_paths:
            print(f"Wrote {path}")
        return

    settings = get_settings()

    if args.command == "import-mlm":
        if (
            settings.environment == Environment.PRODUCTION
            and not settings.mylocalmasjid_enabled
        ):
            print(
                "MyLocalMasjid import is disabled (mylocalmasjid_enabled=false).",
                file=sys.stderr,
            )
            sys.exit(2)
        raise SystemExit(asyncio.run(_run_import_mlm(args, settings)))

    if args.command == "report-mlm":
        raise SystemExit(asyncio.run(_run_report_mlm(args, settings)))

    parser.print_help()
