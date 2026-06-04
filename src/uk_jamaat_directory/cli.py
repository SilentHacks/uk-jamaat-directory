from __future__ import annotations

import argparse

from uk_jamaat_directory import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uk-jamaat-directory",
        description="Operational CLI for the UK Jamaat Directory.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main() -> None:
    parser = build_parser()
    parser.parse_args()
