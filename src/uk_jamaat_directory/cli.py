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
from uk_jamaat_directory.db.cli_session import cli_db_session
from uk_jamaat_directory.db.session import create_engine
from uk_jamaat_directory.ingest.crawl.pipeline import process_source
from uk_jamaat_directory.ingest.crawl.register import ensure_standard_feed_sources
from uk_jamaat_directory.ingest.extract.runner import run_extraction
from uk_jamaat_directory.ingest.extract.standard_feed import extract_standard_feed
from uk_jamaat_directory.ingest.fetch import fetch_url
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
from uk_jamaat_directory.models.core import MosqueSource, SourceArtifact
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
    _add_crawl_parsers(subparsers)

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


def _add_crawl_parsers(subparsers: argparse._SubParsersAction) -> None:
    subparsers.add_parser(
        "register-crawl-sources",
        help="Create standard_feed mosque sources from active mosque website URLs",
    )

    fetch_source = subparsers.add_parser(
        "fetch-source",
        help="Fetch one crawl source URL (respects robots.txt)",
    )
    fetch_source.add_argument("--source-id", required=True, type=uuid.UUID)

    process_source = subparsers.add_parser(
        "process-source",
        help="Fetch and extract schedule candidates for one crawl source",
    )
    process_source.add_argument("--source-id", required=True, type=uuid.UUID)
    process_source.add_argument(
        "--force",
        action="store_true",
        help="Fetch even if next_fetch_at is in the future",
    )

    extract_artifact = subparsers.add_parser(
        "extract-artifact",
        help="Re-run extraction for a stored source artifact",
    )
    extract_artifact.add_argument("--artifact-id", required=True, type=uuid.UUID)

    fetch_feed = subparsers.add_parser(
        "fetch-feed",
        help="Fetch a standard feed URL without writing to the database",
    )
    fetch_feed.add_argument("--url", required=True)
    fetch_feed.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse feed body and print row count only",
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

    if args.command == "register-crawl-sources":
        raise SystemExit(asyncio.run(_run_register_crawl_sources(settings)))

    if args.command == "fetch-source":
        raise SystemExit(asyncio.run(_run_fetch_source(args, settings)))

    if args.command == "process-source":
        raise SystemExit(asyncio.run(_run_process_source(args, settings)))

    if args.command == "extract-artifact":
        raise SystemExit(asyncio.run(_run_extract_artifact(args, settings)))

    if args.command == "fetch-feed":
        raise SystemExit(asyncio.run(_run_fetch_feed(args, settings)))

    parser.print_help()


async def _run_validate_candidates(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        result = await validate_candidates(
            session,
            source_id=args.source_id,
            mosque_id=args.mosque_id,
            date_from=args.date_from,
            date_to=args.date_to,
            update_status=not args.dry_run,
        )
        await session.commit()

    print(
        f"Validated {result.examined} candidates: "
        f"approved={result.approved}, rejected={result.rejected}, "
        f"pending={result.pending}, skipped={result.skipped}"
    )
    return 0


async def _run_publish_candidates(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        result = await publish_candidates(
            session,
            source_id=args.source_id,
            mosque_id=args.mosque_id,
            date_from=args.date_from,
            date_to=args.date_to,
            settings=settings,
        )
        await session.commit()

    print(
        f"Published {result.published} occurrences "
        f"(carried_forward={result.carried_forward}, "
        f"dataset={result.dataset_version}, "
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
    if result.published == 0 and result.carried_forward == 0:
        return 1
    return 0


async def _run_recompute_freshness(settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        count = await recompute_all_source_health(session)
        await session.commit()

    print(f"Recomputed freshness for {count} public sources")
    return 0


async def _run_register_crawl_sources(settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        result = await ensure_standard_feed_sources(session, settings=settings)
        await session.commit()

    print(
        "Crawl source registration: "
        f"created={result.created}, "
        f"skipped_existing={result.skipped_existing}, "
        f"skipped_mlm={result.skipped_mlm}, "
        f"skipped_no_domain={result.skipped_no_domain}"
    )
    return 0


async def _run_fetch_source(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        source = await session.get(MosqueSource, args.source_id)
        if source is None or not source.source_url:
            print("Source not found or missing source_url", file=sys.stderr)
            return 1
        from uk_jamaat_directory.ingest.artifacts import latest_artifact_for_source

        prior = await latest_artifact_for_source(session, source.id)
        fetch = await fetch_url(source.source_url, prior_artifact=prior, settings=settings)

    print(
        f"Fetch {source.source_url}: "
        f"status={fetch.status_code}, unchanged={fetch.unchanged}, "
        f"bytes={len(fetch.body)}, error={fetch.error}"
    )
    return 0 if fetch.ok else 1


async def _run_process_source(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        result = await process_source(
            session,
            args.source_id,
            settings=settings,
            force=args.force,
        )
        await session.commit()

    print(
        f"Process source {result.source_id}: "
        f"fetched={result.fetched}, unchanged={result.unchanged}, "
        f"artifact_created={result.artifact_created}, extracted={result.extracted}, "
        f"candidates_created={result.candidates_created}, "
        f"skipped={result.skipped_reason}, error={result.error}"
    )
    if result.warnings:
        for warning in result.warnings[:10]:
            print(f"  warning: {warning}", file=sys.stderr)
    return 0 if result.error is None else 1


async def _run_extract_artifact(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        artifact = await session.get(SourceArtifact, args.artifact_id)
        if artifact is None:
            print("Artifact not found", file=sys.stderr)
            return 1
        source = await session.get(MosqueSource, artifact.source_id)
        if source is None:
            print("Source not found", file=sys.stderr)
            return 1
        extraction = await run_extraction(session, artifact, source, settings=settings)
        await session.commit()

    print(
        f"Extraction {extraction.extraction_run_id}: status={extraction.status}, "
        f"candidates_created={extraction.candidates_created}, "
        f"skipped={extraction.candidates_skipped}"
    )
    if extraction.errors:
        for error in extraction.errors:
            print(f"  error: {error}", file=sys.stderr)
        return 1
    return 0


async def _run_fetch_feed(args: argparse.Namespace, settings: Settings) -> int:
    fetch = await fetch_url(args.url, settings=settings)
    if not fetch.ok:
        print(f"Fetch failed: {fetch.error}", file=sys.stderr)
        return 1

    if args.dry_run:
        result = extract_standard_feed(fetch.body)
        print(
            f"Dry run OK: rows={len(result.rows)}, warnings={len(result.warnings)}, "
            f"extractor={result.extractor_version}"
        )
        return 0

    print(fetch.body.decode("utf-8", errors="replace"))
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
