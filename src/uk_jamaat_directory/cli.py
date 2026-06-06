from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from uk_jamaat_directory import __version__
from uk_jamaat_directory.config import Environment, Settings, get_settings
from uk_jamaat_directory.db.cli_session import cli_db_session
from uk_jamaat_directory.db.session import create_engine
from uk_jamaat_directory.exports import generate_dataset_exports
from uk_jamaat_directory.ingest.crawl.pipeline import process_source
from uk_jamaat_directory.ingest.crawl.register import ensure_standard_feed_sources
from uk_jamaat_directory.ingest.extract.runner import run_extraction
from uk_jamaat_directory.ingest.extract.standard_feed import extract_standard_feed
from uk_jamaat_directory.ingest.fetch import fetch_url
from uk_jamaat_directory.ingest.policy import parse_publication_policy
from uk_jamaat_directory.ingest.sources.muslimsinbritain import (
    build_coverage_report as build_mib_coverage_report,
)
from uk_jamaat_directory.ingest.sources.muslimsinbritain import (
    export_mib_bundle,
    import_muslimsinbritain_bundle,
    parse_mib_file,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid import (
    build_coverage_report as build_mlm_coverage_report,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid import (
    import_mylocalmasjid_bundle,
)
from uk_jamaat_directory.ingest.sources.mylocalmasjid.adapter import ImportFormat, parse_file
from uk_jamaat_directory.ingest.sources.openstreetmap import (
    export_osm_bundle,
    import_openstreetmap_bundle,
    parse_osm_file,
)
from uk_jamaat_directory.ingest.sources.openstreetmap.adapter import validate_osm_bundle
from uk_jamaat_directory.models.core import MosqueSource, SourceArtifact
from uk_jamaat_directory.schedules import (
    publish_candidates,
    recompute_all_source_health,
    validate_candidates,
)
from uk_jamaat_directory.services import admin_identity, admin_reporting
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

    export_mib = subparsers.add_parser(
        "export-mib",
        help="Fetch the MuslimsInBritain UK and Ireland directory and write import-mib JSON",
    )
    export_mib.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path for the normalized MibImportBundle JSON file",
    )
    export_mib.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate without writing the output file",
    )
    export_mib.add_argument(
        "--enrich-details",
        action="store_true",
        help="Reserved for slower per-entry detail enrichment when needed",
    )

    import_mib = subparsers.add_parser(
        "import-mib",
        help="Import a MuslimsInBritain UK and Ireland JSON/CSV export into mosque sources",
    )
    import_mib.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to MiB export file (synthetic fixtures for local testing)",
    )
    import_mib.add_argument(
        "--publication-policy",
        default=None,
        help=(
            "Source publication policy for imported rows "
            "(public_redistribution_allowed, private_use_only, unknown, blocked). "
            "Defaults to MUSLIMSINBRITAIN_PUBLICATION_POLICY or 'unknown'."
        ),
    )
    import_mib.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate the file without writing to the database",
    )

    report_mib = subparsers.add_parser(
        "report-mib",
        help="Summarize MuslimsInBritain source coverage, linkage, and review backlog",
    )
    report_mib.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human summary",
    )

    import_osm = subparsers.add_parser(
        "import-osm",
        help="Import OSM UK and Ireland Muslim places of worship from a JSON fixture/export",
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

    export_osm = subparsers.add_parser(
        "export-osm",
        help=(
            "Fetch UK and Ireland Muslim places of worship from Overpass and write import-osm JSON"
        ),
    )
    export_osm.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path for the normalized OsmImportBundle JSON file",
    )
    export_osm.add_argument(
        "--overpass-url",
        default=None,
        help="Override the Overpass interpreter URL from settings",
    )
    export_osm.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate without writing the output file",
    )

    _add_schedule_candidate_parsers(subparsers)
    _add_identity_parsers(subparsers)
    _add_crawl_parsers(subparsers)
    _add_export_parsers(subparsers)
    _add_backfill_parsers(subparsers)

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


def _add_identity_parsers(subparsers: argparse._SubParsersAction) -> None:
    identity_report = subparsers.add_parser(
        "identity-report",
        help="Report identity quality, source overlap, review backlog, and missing fields",
    )
    identity_report.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a human summary",
    )

    list_reviews = subparsers.add_parser(
        "list-identity-reviews",
        help="List pending identity match reviews with candidate mosques",
    )
    list_reviews.add_argument("--status", default="pending")
    list_reviews.add_argument("--source-type", default=None)
    list_reviews.add_argument(
        "--reason",
        default=None,
        help=(
            "Filter to reviews whose reasons array contains this token "
            "(e.g. parent_org_source, name_evidence_override, "
            "high_score_insufficient_signals, below_auto_link_threshold)."
        ),
    )
    list_reviews.add_argument("--limit", type=int, default=50)
    list_reviews.add_argument("--offset", type=int, default=0)
    list_reviews.add_argument("--json", action="store_true")

    accept_review = subparsers.add_parser(
        "accept-identity-review",
        help="Link an identity review source to a selected canonical mosque",
    )
    accept_review.add_argument("--review-id", required=True, type=uuid.UUID)
    accept_review.add_argument("--mosque-id", type=uuid.UUID, default=None)
    accept_review.add_argument("--reason", default=None)

    reject_review = subparsers.add_parser(
        "reject-identity-review",
        help="Reject a pending identity match review",
    )
    reject_review.add_argument("--review-id", required=True, type=uuid.UUID)
    reject_review.add_argument("--reason", default=None)

    bulk_accept = subparsers.add_parser(
        "bulk-accept-identity-reviews",
        help="Accept high-confidence identity reviews with exactly one candidate",
    )
    bulk_accept.add_argument("--min-score", type=float, default=0.8)
    bulk_accept.add_argument("--limit", type=int, default=100)
    bulk_accept.add_argument("--dry-run", action="store_true")

    bulk_activate = subparsers.add_parser(
        "activate-reviewed-mosques",
        help="Mark reviewed needs_review mosques active for downstream crawl/public workflows",
    )
    bulk_activate.add_argument("--source-type", default=None)
    bulk_activate.add_argument("--limit", type=int, default=1000)
    bulk_activate.add_argument("--dry-run", action="store_true")
    bulk_activate.add_argument(
        "--include-private-sources",
        action="store_true",
        help="Allow activation of mosques that have no public-redistribution source",
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


def _add_export_parsers(subparsers: argparse._SubParsersAction) -> None:
    generate_exports = subparsers.add_parser(
        "generate-exports",
        help="Build NDJSON/CSV snapshot files for a published dataset version",
    )
    generate_exports.add_argument(
        "--version",
        default=None,
        help="Dataset version name (defaults to latest published)",
    )
    generate_exports.add_argument(
        "--version-id",
        type=uuid.UUID,
        default=None,
        help="Dataset version UUID (overrides --version)",
    )


def _add_backfill_parsers(subparsers: argparse._SubParsersAction) -> None:
    backfill_mib = subparsers.add_parser(
        "backfill-mib-websites",
        help=(
            "Promote MiB metadata_.website_url onto linked mosques. "
            "Honours the same only_empty rule as the import path."
        ),
    )
    backfill_mib.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts without writing to the database",
    )

    discover_websites = subparsers.add_parser(
        "discover-websites",
        help=(
            "Run Phase 5 website discovery over mosques with no website_url. "
            "Defaults to the MiB metadata walk; pass --provider to add others."
        ),
    )
    discover_websites.add_argument(
        "--provider",
        action="append",
        choices=("mib_metadata", "osm_tag_recheck", "charity_commission", "oscr", "search_engine"),
        help=(
            "Lead source(s) to include. May be passed multiple times. "
            "``charity_commission`` requires ``--charity-file`` pointing at "
            "the daily extract TSV; ``oscr`` requires ``--oscr-file``. "
            "``search_engine`` requires ``--exa-api-key`` or ``EXA_SEARCH_API_KEY``."
        ),
    )
    discover_websites.add_argument(
        "--charity-file",
        type=Path,
        default=None,
        help=(
            "Path to the Charity Commission for England and Wales daily "
            "TSV extract (publicextract.charity.txt). Required for "
            "``--provider charity_commission``."
        ),
    )
    discover_websites.add_argument(
        "--oscr-file",
        type=Path,
        default=None,
        help=(
            "Path to the Office of the Scottish Charity Regulator daily "
            "CSV export (CharityExport-<date>.csv). Required for "
            "``--provider oscr``."
        ),
    )
    discover_websites.add_argument(
        "--exa-api-key",
        default=None,
        help="Exa Search API key (overrides EXA_SEARCH_API_KEY from .env)",
    )
    discover_websites.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only search the first N mosques (useful for trial runs)",
    )
    discover_websites.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the providers and verification but do not write promotions",
    )


def _resolve_mlm_policy(args: argparse.Namespace, settings: Settings):
    raw = args.publication_policy or settings.mylocalmasjid_publication_policy
    return parse_publication_policy(raw)


def _resolve_mib_policy(args: argparse.Namespace, settings: Settings):
    raw = args.publication_policy or settings.muslimsinbritain_publication_policy
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
            report = await build_mlm_coverage_report(session)
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


async def _run_export_mib(args: argparse.Namespace, settings: Settings) -> int:
    try:
        bundle, result = await export_mib_bundle(
            None if args.dry_run else args.output,
            dry_run=args.dry_run,
            enrich_details=args.enrich_details,
            settings=settings,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"MiB export failed: {exc}", file=sys.stderr)
        return 1

    skip_summary = _format_skip_reasons(result.skip_reasons)
    detail_summary = ""
    if args.enrich_details:
        detail_summary = (
            f", detail_pages_enriched={result.detail_pages_enriched}, "
            f"detail_pages_failed={result.detail_pages_failed}"
        )
    print(
        "MiB export complete: "
        f"{len(bundle.mosques)} records written, "
        f"{result.records_skipped} skipped{skip_summary}{detail_summary}"
    )
    if not args.dry_run and result.output_path is not None:
        print(f"Wrote {result.output_path}")
    return 0


async def _run_import_mib(args: argparse.Namespace, settings: Settings) -> int:
    bundle = parse_mib_file(args.input)
    policy = _resolve_mib_policy(args, settings)
    if args.dry_run:
        print(f"Dry run OK: {len(bundle.mosques)} MiB records, policy={policy.value}")
        return 0

    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await import_muslimsinbritain_bundle(
                session,
                bundle,
                publication_policy=policy,
            )
            await session.commit()
    finally:
        await engine.dispose()

    print(
        "MiB import complete: "
        f"{result.records_processed} records, "
        f"{result.mosques_created} mosques created, "
        f"{result.mosques_linked} linked, "
        f"{result.reviews_created} reviews, "
        f"{result.skipped} skipped"
    )
    if result.errors:
        print("Errors:", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    return 0


async def _run_report_mib(args: argparse.Namespace, settings: Settings) -> int:
    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            report = await build_mib_coverage_report(session)
    finally:
        await engine.dispose()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    print(f"MuslimsInBritain coverage report ({report.generated_at.isoformat()})")
    print(f"  Sources: {report.source_count} ({report.linked_mosque_count} linked to mosques)")
    print(f"  Countries: {report.country_counts or '(none)'}")
    print(f"  Record classes: {report.record_class_counts or '(none)'}")
    print(f"  Publication policies: {report.policy_counts or '(none)'}")
    print(f"  Pending identity reviews: {report.pending_reviews}")
    print(f"  Missing coordinates: {len(report.missing_coordinates)}")
    print(f"  Missing postcodes: {len(report.missing_postcode)}")
    print(f"  Stale sources (>{settings.mib_report_stale_days} days): {len(report.stale_sources)}")
    print(f"  Attribution: {report.attribution_summary}")
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

    if args.command == "export-mib":
        raise SystemExit(asyncio.run(_run_export_mib(args, settings)))

    if args.command == "import-mib":
        if settings.environment == Environment.PRODUCTION and not settings.muslimsinbritain_enabled:
            print(
                "MuslimsInBritain import is disabled (muslimsinbritain_enabled=false).",
                file=sys.stderr,
            )
            sys.exit(2)
        raise SystemExit(asyncio.run(_run_import_mib(args, settings)))

    if args.command == "report-mib":
        raise SystemExit(asyncio.run(_run_report_mib(args, settings)))

    if args.command == "import-osm":
        raise SystemExit(asyncio.run(_run_import_osm(args, settings)))

    if args.command == "export-osm":
        raise SystemExit(asyncio.run(_run_export_osm(args, settings)))

    if args.command == "validate-candidates":
        raise SystemExit(asyncio.run(_run_validate_candidates(args, settings)))

    if args.command == "publish-candidates":
        raise SystemExit(asyncio.run(_run_publish_candidates(args, settings)))

    if args.command == "recompute-freshness":
        raise SystemExit(asyncio.run(_run_recompute_freshness(settings)))

    if args.command == "identity-report":
        raise SystemExit(asyncio.run(_run_identity_report(args, settings)))

    if args.command == "list-identity-reviews":
        raise SystemExit(asyncio.run(_run_list_identity_reviews(args, settings)))

    if args.command == "accept-identity-review":
        raise SystemExit(asyncio.run(_run_accept_identity_review(args, settings)))

    if args.command == "reject-identity-review":
        raise SystemExit(asyncio.run(_run_reject_identity_review(args, settings)))

    if args.command == "bulk-accept-identity-reviews":
        raise SystemExit(asyncio.run(_run_bulk_accept_identity_reviews(args, settings)))

    if args.command == "activate-reviewed-mosques":
        raise SystemExit(asyncio.run(_run_activate_reviewed_mosques(args, settings)))

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

    if args.command == "generate-exports":
        raise SystemExit(asyncio.run(_run_generate_exports(args, settings)))
    if args.command == "backfill-mib-websites":
        raise SystemExit(asyncio.run(_run_backfill_mib_websites(args, settings)))
    if args.command == "discover-websites":
        raise SystemExit(asyncio.run(_run_discover_websites(args, settings)))

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


async def _run_identity_report(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        report = await admin_reporting.build_identity_quality_report(session)

    payload = {
        "generated_at": report.generated_at.isoformat(),
        "mosque_count": report.mosque_count,
        "active_mosque_count": report.active_mosque_count,
        "status_counts": report.status_counts,
        "source_count": report.source_count,
        "source_type_counts": report.source_type_counts,
        "policy_counts": report.policy_counts,
        "source_overlaps": [
            {"source_set": item.source_set, "mosque_count": item.mosque_count}
            for item in report.source_overlaps
        ],
        "linked_source_count": report.linked_source_count,
        "unlinked_source_count": report.unlinked_source_count,
        "pending_identity_reviews": report.pending_identity_reviews,
        "missing_postcode_count": report.missing_postcode_count,
        "missing_coordinates_count": report.missing_coordinates_count,
        "missing_website_count": report.missing_website_count,
        "active_missing_website_count": report.active_missing_website_count,
        "duplicate_candidate_count": report.duplicate_candidate_count,
        "duplicate_buckets": [
            {
                "normalized_name": item.normalized_name,
                "postcode": item.postcode,
                "mosque_count": item.mosque_count,
                "mosque_ids": [str(mosque_id) for mosque_id in item.mosque_ids],
            }
            for item in report.duplicate_buckets
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Identity quality report ({report.generated_at.isoformat()})")
    print(f"  Mosques: {report.mosque_count} active={report.active_mosque_count}")
    print(f"  Statuses: {report.status_counts or '(none)'}")
    print(
        f"  Sources: {report.source_count} linked={report.linked_source_count} "
        f"unlinked={report.unlinked_source_count}"
    )
    print(f"  Source types: {report.source_type_counts or '(none)'}")
    print(f"  Source policies: {report.policy_counts or '(none)'}")
    print(f"  Pending identity reviews: {report.pending_identity_reviews}")
    print(
        "  Missing fields: "
        f"postcode={report.missing_postcode_count}, "
        f"coordinates={report.missing_coordinates_count}, "
        f"website={report.missing_website_count}, "
        f"active_missing_website={report.active_missing_website_count}"
    )
    print(f"  Duplicate candidate mosques: {report.duplicate_candidate_count}")
    print("  Source overlaps:")
    for item in report.source_overlaps[:12]:
        print(f"    - {item.source_set}: {item.mosque_count}")
    if report.duplicate_buckets:
        print("  Top duplicate buckets:")
        for item in report.duplicate_buckets[:10]:
            print(
                f"    - {item.normalized_name} / {item.postcode or '(no postcode)'}: "
                f"{item.mosque_count}"
            )
    return 0


async def _run_list_identity_reviews(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        result = await admin_identity.list_identity_reviews(
            session,
            status=args.status,
            source_type=args.source_type,
            reason=args.reason,
            limit=args.limit,
            offset=args.offset,
        )

    payload = [
        {
            "review_id": str(item.review.id),
            "source_id": str(item.review.source_id) if item.review.source_id else None,
            "source_type": item.source.source_type.value if item.source else None,
            "external_id": item.source.external_id if item.source else None,
            "display_name": item.source.display_name if item.source else None,
            "score": float(item.review.score) if item.review.score is not None else None,
            "reasons": list((item.review.reasons or {}).get("reasons") or []),
            "candidates": [
                {
                    "mosque_id": str(candidate.mosque.id),
                    "name": candidate.mosque.name,
                    "status": candidate.mosque.status.value,
                    "postcode": candidate.mosque.postcode,
                    "city": candidate.mosque.city,
                    "score": candidate.score,
                    "reasons": candidate.reasons,
                }
                for candidate in item.candidates
            ],
        }
        for item in result.items
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "items": payload,
                    "count": result.total,
                    "limit": result.limit,
                    "offset": result.offset,
                },
                indent=2,
            )
        )
        return 0

    print(f"Identity reviews: {result.total} total, showing {len(result.items)}")
    for item in payload:
        print(
            f"  {item['review_id']} {item['source_type']}:{item['external_id']} "
            f"score={item['score']} {item['display_name']}"
        )
        for candidate in item["candidates"]:
            print(
                f"    - {candidate['mosque_id']} score={candidate['score']} "
                f"{candidate['name']} ({candidate['postcode'] or 'no postcode'})"
            )
    return 0


async def _run_accept_identity_review(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        review = await admin_identity.accept_identity_review(
            session,
            args.review_id,
            mosque_id=args.mosque_id,
            actor="cli",
            reason=args.reason,
        )
        await session.commit()
    print(f"Accepted identity review {review.id} -> mosque {review.proposed_mosque_id}")
    return 0


async def _run_reject_identity_review(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        review = await admin_identity.reject_identity_review(
            session,
            args.review_id,
            actor="cli",
            reason=args.reason,
        )
        await session.commit()
    print(f"Rejected identity review {review.id}")
    return 0


async def _run_bulk_accept_identity_reviews(
    args: argparse.Namespace,
    settings: Settings,
) -> int:
    async with cli_db_session(settings) as session:
        result = await admin_identity.bulk_accept_identity_reviews(
            session,
            min_score=args.min_score,
            limit=args.limit,
            dry_run=args.dry_run,
            actor="cli",
        )
        if not args.dry_run:
            await session.commit()
    mode = "would accept" if result.dry_run else "accepted"
    print(f"Bulk identity reviews: {mode} {result.changed}")
    return 0


async def _run_activate_reviewed_mosques(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        result = await admin_identity.bulk_activate_reviewed_mosques(
            session,
            source_type=args.source_type,
            require_public_source=not args.include_private_sources,
            limit=args.limit,
            dry_run=args.dry_run,
            actor="cli",
        )
        if not args.dry_run:
            await session.commit()
    mode = "would activate" if result.dry_run else "activated"
    print(f"Reviewed mosques: {mode} {result.changed}")
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


async def _run_generate_exports(args: argparse.Namespace, settings: Settings) -> int:
    async with cli_db_session(settings) as session:
        result = await generate_dataset_exports(
            session,
            version_name=args.version,
            version_id=args.version_id,
            settings=settings,
        )
        await session.commit()

    if result.errors:
        for error in result.errors:
            print(f"Error: {error}", file=sys.stderr)
        return 1

    print(
        f"Generated exports for {result.version}: "
        f"files={result.files_written}, "
        f"mosques={result.mosque_count}, "
        f"occurrences={result.occurrence_count}, "
        f"changes={result.change_count}, "
        f"checksum={result.checksum}"
    )
    return 0


def _format_skip_reasons(skip_reasons: Mapping[str, int]) -> str:
    if not skip_reasons:
        return ""
    parts = [f"{reason}={count}" for reason, count in sorted(skip_reasons.items())]
    return f" ({', '.join(parts)})"


async def _run_export_osm(args: argparse.Namespace, settings: Settings) -> int:
    try:
        bundle, result = await export_osm_bundle(
            None if args.dry_run else args.output,
            overpass_url=args.overpass_url,
            dry_run=args.dry_run,
            settings=settings,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"OSM export failed: {exc}", file=sys.stderr)
        return 1

    validate_osm_bundle(bundle)
    if not args.dry_run:
        parse_osm_file(args.output)

    skip_summary = _format_skip_reasons(result.skip_reasons)
    print(
        "OSM export complete: "
        f"{result.places_written} places written, "
        f"{result.places_skipped} skipped{skip_summary}"
    )
    if not args.dry_run and result.output_path is not None:
        print(f"Wrote {result.output_path}")
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


async def _run_backfill_mib_websites(args: argparse.Namespace, settings: Settings) -> int:
    from uk_jamaat_directory.services.mib_backfill import backfill_mib_websites

    async with cli_db_session(settings) as session:
        result = await backfill_mib_websites(session, dry_run=args.dry_run)
        if not args.dry_run:
            await session.commit()

    mode = "DRY RUN" if args.dry_run else "applied"
    print(
        f"MiB website backfill {mode}: "
        f"candidates={result.candidates} "
        f"updated={result.updated} "
        f"skipped_already_set={result.skipped_already_set} "
        f"skipped_no_mosque={result.skipped_no_mosque} "
        f"skipped_no_website_in_metadata={result.skipped_no_website_in_metadata} "
        f"errors={len(result.errors)}"
    )
    if result.errors:
        print("Errors:", file=sys.stderr)
        for error in result.errors[:20]:
            print(f"  - {error}", file=sys.stderr)
        return 1
    return 0


async def _run_discover_websites(args: argparse.Namespace, settings: Settings) -> int:
    from uk_jamaat_directory.ingest.discovery.websites.providers.charity_commission import (
        propose_charity_commission_leads,
    )
    from uk_jamaat_directory.ingest.discovery.websites.providers.charity_index import (
        load_charity_index,
        load_oscr_index,
    )
    from uk_jamaat_directory.ingest.discovery.websites.providers.mib_metadata import (
        propose_mib_metadata_leads,
    )
    from uk_jamaat_directory.ingest.discovery.websites.providers.oscr import (
        propose_oscr_leads,
    )
    from uk_jamaat_directory.ingest.discovery.websites.providers.osm_tag_recheck import (
        propose_osm_tag_leads,
    )
    from uk_jamaat_directory.services.website_discovery import run_website_discovery

    available = {
        "mib_metadata": propose_mib_metadata_leads,
        "osm_tag_recheck": propose_osm_tag_leads,
    }
    selected: list[object] | None = None
    charity_index: dict | None = None
    oscr_index: dict | None = None
    if getattr(args, "provider", None):
        selected = []
        for name in args.provider:
            if name == "charity_commission":
                if not args.charity_file:
                    print(
                        "error: --provider charity_commission requires --charity-file <path>",
                        file=sys.stderr,
                    )
                    return 2
                if charity_index is None:
                    charity_index = load_charity_index(args.charity_file)

                async def _run_with_cc_index(session, _index=charity_index):
                    return await propose_charity_commission_leads(session, charity_index=_index)

                selected.append(_run_with_cc_index)
            elif name == "oscr":
                if not args.oscr_file:
                    print(
                        "error: --provider oscr requires --oscr-file <path>",
                        file=sys.stderr,
                    )
                    return 2
                if oscr_index is None:
                    oscr_index = load_oscr_index(args.oscr_file)

                async def _run_with_oscr_index(session, _index=oscr_index):
                    return await propose_oscr_leads(session, charity_index=_index)

                selected.append(_run_with_oscr_index)
            elif name == "search_engine":
                from uk_jamaat_directory.ingest.discovery.websites.providers.search_engine import (
                    propose_search_engine_leads,
                )
                from uk_jamaat_directory.ingest.discovery.websites.search.cache import (
                    SearchCache,
                )
                from uk_jamaat_directory.ingest.discovery.websites.search.exa_client import (
                    ExaClient,
                )

                api_key = args.exa_api_key or settings.exa_search_api_key
                if not api_key:
                    print(
                        "error: --provider search_engine requires --exa-api-key "
                        "or EXA_SEARCH_API_KEY in .env",
                        file=sys.stderr,
                    )
                    return 2
                client = ExaClient(
                    api_key=api_key,
                    max_concurrency=settings.search_engine_max_concurrency,
                )
                cache = SearchCache()

                async def _run_with_search(
                    session,
                    _client=client,
                    _cache=cache,
                    _limit=args.limit,
                ):
                    try:
                        return await propose_search_engine_leads(
                            session,
                            exa_client=_client,
                            cache=_cache,
                            max_concurrency=settings.search_engine_max_concurrency,
                            limit=_limit,
                        )
                    finally:
                        await _client.aclose()

                selected.append(_run_with_search)
            else:
                selected.append(available[name])

    async with cli_db_session(settings) as session:
        result = await run_website_discovery(
            session,
            providers=selected,
            actor="discover_websites_cli",
        )
        if not args.dry_run:
            await session.commit()

    print(
        f"Phase 5 website discovery: "
        f"verified={result.verified} "
        f"promoted={result.promoted} "
        f"denied={result.denied} "
        f"fetch_failed={result.fetch_failed} "
        f"no_match={result.no_match} "
        f"leads_recorded={result.leads_recorded}"
    )
    for name, provider_result in result.providers.items():
        print(f"  provider {name}: proposed={provider_result.candidates_proposed}")
    if result.errors:
        print("Errors:", file=sys.stderr)
        for error in result.errors[:20]:
            print(f"  - {error}", file=sys.stderr)
        return 1
    return 0
