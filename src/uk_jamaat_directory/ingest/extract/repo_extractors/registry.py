from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
)

_SCRIPT_PACKAGE = "uk_jamaat_directory.ingest.extract.repo_extractors.scripts"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegisteredExtractor:
    module_name: str
    extractor: BaseMosqueWebsiteExtractor


def iter_script_modules() -> list[str]:
    package = importlib.import_module(_SCRIPT_PACKAGE)
    names: list[str] = []
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name.startswith("_"):
            continue
        names.append(f"{_SCRIPT_PACKAGE}.{module_info.name}")
    return names


def load_all_extractors(*, reload: bool = False) -> list[RegisteredExtractor]:
    """Load every extractor script.

    ``reload=True`` re-imports already-loaded script modules so freshly
    rewritten scripts (authoring repair loop) are picked up.
    """
    importlib.invalidate_caches()
    registered: list[RegisteredExtractor] = []
    for module_name in iter_script_modules():
        # A broken script (e.g. a draft an agent is still repairing) must not
        # take down the whole registry; skip it.
        try:
            module = importlib.import_module(module_name)
            if reload:
                module = importlib.reload(module)
            extractor_cls = getattr(module, "Extractor", None)
            if extractor_cls is None:
                continue
            instance = extractor_cls()
        except Exception:  # noqa: BLE001
            logger.warning("skipping unloadable extractor module %s", module_name)
            continue
        if not isinstance(instance, BaseMosqueWebsiteExtractor):
            continue
        registered.append(RegisteredExtractor(module_name=module_name, extractor=instance))
    return registered


def find_extractor_for_source(
    *,
    domain: str | None,
    mosque_name: str | None,
) -> list[RegisteredExtractor]:
    matches: list[RegisteredExtractor] = []
    for entry in load_all_extractors():
        if entry.extractor.source_match.matches(domain=domain, name=mosque_name):
            matches.append(entry)
    return matches
