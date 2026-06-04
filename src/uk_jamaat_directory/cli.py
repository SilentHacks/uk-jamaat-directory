from __future__ import annotations

import argparse
from pathlib import Path

from uk_jamaat_directory import __version__
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
    return parser


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
