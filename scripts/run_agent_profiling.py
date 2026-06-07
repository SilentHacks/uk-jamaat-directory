#!/usr/bin/env python3
"""Standalone host-side agent profiling runner.

Runs the asyncio orchestrator in a completely independent process.
Use this in a real terminal (outside OpenCode), ideally inside screen/tmux,
for overnight batch profiling.

Usage:
    screen -dmS agent-profile \
        .venv/bin/python scripts/run_agent_profiling.py \
        --limit 1500 --concurrency 5 --timeout 120 --max-pages 10 \
        --output-dir data/agent_profiles/overnight_001

Monitor progress in another terminal:
    cat data/agent_profiles/overnight_001/metrics.json
    cat data/agent_profiles/overnight_001/state.json
    cat data/agent_profiles/overnight_001/orchestrator.log
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure src is on PYTHONPATH when run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from uk_jamaat_directory.config import get_settings
from uk_jamaat_directory.db.cli_session import cli_db_session
from uk_jamaat_directory.ingest.extract.ai.agent_orchestrator import (
    run_agent_profiling,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run agent profiling in background")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    async with cli_db_session(settings) as session:
        result = await run_agent_profiling(
            session,
            settings,
            limit=args.limit,
            concurrency=args.concurrency,
            timeout=args.timeout,
            max_pages=args.max_pages,
            output_dir=args.output_dir,
            force=args.force,
        )

    print(
        f"Finished: attempted={result.attempted}, ready={result.succeeded}, "
        f"review_needed={result.review_needed}, failed={result.failed}"
    )
    if result.output_dir:
        print(f"Output: {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
