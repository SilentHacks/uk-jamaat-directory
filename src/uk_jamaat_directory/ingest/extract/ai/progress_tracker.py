from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from uk_jamaat_directory.config import Settings

DEFAULT_PROGRESS_PATH = "data/profiling_progress.json"


@dataclass
class ProfilingRun:
    run_id: str
    started_at: str
    batch_size: int
    completed_source_ids: list[str] = field(default_factory=list)
    failed_source_ids: dict[str, str] = field(default_factory=dict)
    current_batch: int = 0
    batch_dirs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "batch_size": self.batch_size,
            "completed_source_ids": self.completed_source_ids,
            "failed_source_ids": self.failed_source_ids,
            "current_batch": self.current_batch,
            "batch_dirs": self.batch_dirs,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProfilingRun:
        return cls(**data)


def progress_path(settings: Settings | None = None) -> str:
    _ = settings  # placeholder for future config-driven path
    return DEFAULT_PROGRESS_PATH


def init_run(batch_size: int = 10) -> ProfilingRun:
    return ProfilingRun(
        run_id=datetime.now(UTC).strftime("run_%Y%m%d_%H%M%S"),
        started_at=datetime.now(UTC).isoformat(),
        batch_size=batch_size,
    )


def save_run(run: ProfilingRun, path: str | None = None) -> None:
    p = Path(path or DEFAULT_PROGRESS_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(run.to_dict(), indent=2))


def load_run(path: str | None = None) -> ProfilingRun | None:
    p = Path(path or DEFAULT_PROGRESS_PATH)
    if not p.exists():
        return None
    try:
        return ProfilingRun.from_dict(json.loads(p.read_text()))
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def mark_completed(run: ProfilingRun, source_id: str) -> None:
    if source_id not in run.completed_source_ids:
        run.completed_source_ids.append(source_id)
    run.failed_source_ids.pop(source_id, None)


def mark_failed(run: ProfilingRun, source_id: str, reason: str) -> None:
    if source_id not in run.completed_source_ids:
        run.failed_source_ids[source_id] = reason


def next_batch_dir(run: ProfilingRun, base_dir: str = "data/profiling_batches") -> str:
    run.current_batch += 1
    d = f"{base_dir}/{run.run_id}/batch_{run.current_batch:04d}"
    run.batch_dirs.append(d)
    return d
