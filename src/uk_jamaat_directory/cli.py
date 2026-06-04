from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from uk_jamaat_directory import __version__
from uk_jamaat_directory.config import Environment, Settings, get_settings
from uk_jamaat_directory.db.session import create_engine
from uk_jamaat_directory.ingest.policy import parse_publication_policy
from uk_jamaat_directory.ingest.sources.mylocalmasjid import (
    build_coverage_report,
    import_mylocalmasjid_bundle,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid.adapter import ImportFormat, parse_file
from uk_jamaat_directory.ingest.sources.openstreetmap import (
    import_openstreetmap_bundle,
    parse_osm_file,
)
from uk_jamaat_directory.schedules import (
    publish_candidates,
    recompute_all_source_health,
    validate_candidates,
)
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
    import_mlm.add_argument(
        "--validate",
        action="store_true",
        help="Run schedule validation after import (does not publish)",
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

    import_osm = subparsers.add_parser(
        "import-osm",
        help="Import OSM GB Muslim places of worship from a JSON fixture/export",
    )
    import_osm.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to OSM places JSON (synthetic fixtures for local testing)",
    )
    import_osm.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the file without writing to the database",
    )

    _add_schedule_candidate_parsers(subparsers)

    return parser


def _parse_optional_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _parse_optional_uuid(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    return uuid.UUID(value)


def _add_schedule_candidate_parsers(subparsers: argparse._SubParsersAction) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--source-id", type=_parse_optional_uuid, default=None)
    common.add_argument("--mosque-id", type=_parse_optional_uuid, default=None)
    common.add_argument("--from", dest="date_from", type=_parse_optional_date, default=None)
    common.add_argument("--to", dest="date_to", type=_parse_optional_date, default=None)

    validate_cmd = subparsers.add_parser(
        "validate-candidates",
        parents=[common],
        help="Validate pending schedule candidates and set approved/rejected status",
    )
    validate_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without updating candidate status",
    )

    subparsers.add_parser(
        "publish-candidates",
        parents=[common],
        help="Publish approved candidates to public schedule occurrences",
    )

    subparsers.add_parser(
        "recompute-freshness",
        help="Recompute source_health for all public-redistribution sources",
    )


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

    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await import_mylocalmasjid_bundle(
                session,
                bundle,
                raw_payload=raw_payload,
                fetched_url=fetched_url,
                publication_policy=policy,
                validate_after_import=args.validate,
            )
            await session.commit()
    finally:
        await engine.dispose()

    print(
        "Import complete: "
        f"{result.mosques_upserted} mosques, "
        f"{result.mosques_linked} linked, "
        f"{result.reviews_created} reviews, "
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
    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            report = await build_coverage_report(session)
    finally:
        await engine.dispose()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    print(f"MyLocalMasjid coverage report ({report.generated_at.isoformat()})")
    print(f"  Sources: {report.source_count} ({report.linked_mosque_count} linked to mosques)")
    print(
        f"  Candidates: pending={report.pending_candidates}, approved={report.approved_candidates}"
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
        if settings.environment == Environment.PRODUCTION and not settings.mylocalmasjid_enabled:
            print(
                "MyLocalMasjid import is disabled (mylocalmasjid_enabled=false).",
                file=sys.stderr,
            )
            sys.exit(2)
        raise SystemExit(asyncio.run(_run_import_mlm(args, settings)))

    if args.command == "report-mlm":
        raise SystemExit(asyncio.run(_run_report_mlm(args, settings)))

    if args.command == "import-osm":
        raise SystemExit(asyncio.run(_run_import_osm(args, settings)))

    if args.command == "validate-candidates":
        raise SystemExit(asyncio.run(_run_validate_candidates(args, settings)))

    if args.command == "publish-candidates":
        raise SystemExit(asyncio.run(_run_publish_candidates(args, settings)))

    if args.command == "recompute-freshness":
        raise SystemExit(asyncio.run(_run_recompute_freshness(settings)))

    parser.print_help()


async def _run_validate_candidates(args: argparse.Namespace, settings: Settings) -> int:
    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await validate_candidates(
                session,
                source_id=args.source_id,
                mosque_id=args.mosque_id,
                date_from=args.date_from,
                date_to=args.date_to,
                update_status=not args.dry_run,
            )
            await session.commit()
    finally:
        await engine.dispose()

    print(
        f"Validated {result.examined} candidates: "
        f"approved={result.approved}, rejected={result.rejected}, "
        f"pending={result.pending}, skipped={result.skipped}"
    )
    return 0


async def _run_publish_candidates(args: argparse.Namespace, settings: Settings) -> int:
    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await publish_candidates(
                session,
                source_id=args.source_id,
                mosque_id=args.mosque_id,
                date_from=args.date_from,
                date_to=args.date_to,
                settings=settings,
            )
            await session.commit()
    finally:
        await engine.dispose()

    print(
        f"Published {result.published} occurrences "
        f"(dataset={result.dataset_version}, "
        f"policy_skipped={result.skipped_policy}, "
        f"validation_skipped={result.skipped_validation}, "
        f"removed={result.removed_occurrences}, "
        f"change_events={result.change_events})"
    )
    if result.errors:
        print("Notes:", file=sys.stderr)
        for error in result.errors[:20]:
            print(f"  - {error}", file=sys.stderr)
        if len(result.errors) > 20:
            print(f"  ... and {len(result.errors) - 20} more", file=sys.stderr)
    if result.skipped_policy and result.published == 0:
        return 1
    return 0


async def _run_recompute_freshness(settings: Settings) -> int:
    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            count = await recompute_all_source_health(session)
            await session.commit()
    finally:
        await engine.dispose()

    print(f"Recomputed freshness for {count} public sources")
    return 0


async def _run_import_osm(args: argparse.Namespace, settings: Settings) -> int:
    bundle = parse_osm_file(args.input)
    if args.dry_run:
        print(f"Dry run OK: {len(bundle.places)} OSM places")
        return 0

    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await import_openstreetmap_bundle(session, bundle)
            await session.commit()
    finally:
        await engine.dispose()

    print(
        "OSM import complete: "
        f"{result.places_processed} places, "
        f"{result.mosques_created} mosques created, "
        f"{result.mosques_linked} linked, "
        f"{result.reviews_created} reviews"
    )
    if result.errors:
        print("Errors:", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    return 0
